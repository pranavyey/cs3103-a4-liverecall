#!/usr/bin/env python3
"""LiveRecall server: revision state, bounded history and incremental recovery.

Run: python solution_server.py --port 8765

The source and public measurement tools are unchanged. This correctness
checkpoint uses a bounded FIFO per client. A queue overflow closes that client
so it can resume from retained history; semantic coalescing is a later phase.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import deque
from dataclasses import dataclass
import json
import math
import time
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed


HISTORY_SECONDS = 60.0
MAX_HISTORY_ITEMS = 32_768
MAX_HISTORY_BYTES = 32 * 1024 * 1024
MAX_ACTIVE_ITEMS = 128
MAX_ACTIVE_BYTES = 4 * 1024 * 1024
MAX_PENDING_ITEMS = 256
MAX_PENDING_BYTES = 2 * 1024 * 1024
MAX_MESSAGE_BYTES = 1024 * 1024
HISTORY_PREFIX = '{"type":"HISTORY","items":['
HISTORY_SUFFIX = ']}'
MAX_CAPTION_BYTES = MAX_MESSAGE_BYTES - len(HISTORY_PREFIX) - len(HISTORY_SUFFIX)


def integer(value: Any, minimum: int = 0) -> bool:
    return type(value) is int and value >= minimum


def finite_number(value: Any) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError):
        return False


def parse_object(raw: str | bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def client_resume(hello: dict[str, Any]) -> tuple[int, int, float]:
    segment, revision = hello.get("last_segment", 0), hello.get("last_revision", 0)
    seconds = hello.get("history_seconds", 30)
    if (not integer(segment) or not integer(revision)
            or not finite_number(seconds) or not 0 <= seconds <= HISTORY_SECONDS):
        raise ValueError("Invalid resume cursor or history window")
    return segment, revision, float(seconds)


@dataclass(frozen=True, slots=True)
class Caption:
    segment: int
    revision: int
    source_ts: float
    final: bool
    wire: str
    size: int
    received_at: float

    @classmethod
    def from_message(cls, message: dict[str, Any], session: str) -> Caption:
        if (message.get("type") != "CAPTION_UPDATE"
                or message.get("session") != session
                or not integer(message.get("segment"), 1)
                or not integer(message.get("revision"), 1)
                or not finite_number(message.get("source_ts"))
                or type(message.get("final")) is not bool
                or not isinstance(message.get("text"), str)):
            raise ValueError("Invalid caption fields")
        # Extra source fields are intentionally ignored. Serialize once and
        # share this immutable string across history and all client queues.
        payload = {
            "type": "CAPTION_UPDATE", "session": session,
            "segment": message["segment"], "revision": message["revision"],
            "source_ts": float(message["source_ts"]),
            "final": message["final"], "text": message["text"],
        }
        wire = json.dumps(payload, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False)
        size = len(wire.encode("utf-8"))
        if size > MAX_CAPTION_BYTES:
            raise ValueError("Caption cannot fit in a recovery frame")
        return cls(payload["segment"], payload["revision"], payload["source_ts"],
                   payload["final"], wire, size, time.monotonic())


class SessionState:
    """Finite state for the single session required by the assignment."""

    def __init__(self, session: str):
        self.session = session
        self.history: deque[Caption] = deque()
        self.finals: dict[int, Caption] = {}
        self.active: dict[int, Caption] = {}
        self.history_bytes = 0
        self.active_bytes = 0
        # First appearances have increasing segment IDs in the source contract.
        # Keep this scalar after eviction so an old segment cannot resurrect.
        self.highest_segment_seen = 0

    def prune(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        while self.history and (
            self.history[0].received_at < now - HISTORY_SECONDS
            or len(self.history) > MAX_HISTORY_ITEMS
            or self.history_bytes > MAX_HISTORY_BYTES
        ):
            old = self.history.popleft()
            self.history_bytes -= old.size
            self.finals.pop(old.segment, None)

    def accept(self, message: dict[str, Any]) -> Caption | None:
        self.prune()
        caption = Caption.from_message(message, self.session)
        previous = self.active.get(caption.segment)
        if caption.segment in self.finals:
            return None  # A final is immutable, even if a later revision arrives.
        if previous is not None:
            if caption.revision <= previous.revision:
                return None
        elif caption.segment <= self.highest_segment_seen:
            return None  # A previously retired/evicted segment.

        next_active_bytes = self.active_bytes - (previous.size if previous else 0)
        if not caption.final:
            next_active_bytes += caption.size
            next_active_count = len(self.active) + (0 if previous else 1)
            if (next_active_count > MAX_ACTIVE_ITEMS
                    or next_active_bytes > MAX_ACTIVE_BYTES):
                raise OverflowError("Active segment capacity exceeded")

        self.highest_segment_seen = max(self.highest_segment_seen, caption.segment)
        if caption.final:
            self.active.pop(caption.segment, None)
            self.active_bytes = next_active_bytes
            self.finals[caption.segment] = caption
            self.history.append(caption)
            self.history_bytes += caption.size
            self.prune()
        else:
            self.active[caption.segment] = caption
            self.active_bytes = next_active_bytes
        return caption

    def snapshot(self, cursor: tuple[int, int], seconds: float
                 ) -> tuple[tuple[Caption, ...], tuple[Caption, ...]]:
        self.prune()
        cutoff = time.time() - seconds
        finals = tuple(sorted(
            (item for item in self.history
             if seconds > 0 and item.source_ts >= cutoff
             and (item.segment, item.revision) > cursor),
            key=lambda item: (item.segment, item.revision),
        ))
        active = tuple(sorted(
            (item for item in self.active.values()
             if (item.segment, item.revision) > cursor),
            key=lambda item: (item.segment, item.revision),
        ))
        return finals, active


def history_frames(items: tuple[Caption, ...]):
    """Keep every final while respecting the supplied clients' 1 MiB limit."""
    parts: list[str] = []
    size = len(HISTORY_PREFIX) + len(HISTORY_SUFFIX)
    emitted = False
    for item in items:
        extra = item.size + (1 if parts else 0)
        if parts and size + extra > MAX_MESSAGE_BYTES:
            yield HISTORY_PREFIX + ",".join(parts) + HISTORY_SUFFIX
            emitted = True
            parts = []
            size = len(HISTORY_PREFIX) + len(HISTORY_SUFFIX)
        size += item.size + (1 if parts else 0)
        parts.append(item.wire)
    if parts or not emitted:
        yield HISTORY_PREFIX + ",".join(parts) + HISTORY_SUFFIX


class ClientSender:
    def __init__(self, ws: Any, history: tuple[Caption, ...],
                 active: tuple[Caption, ...]):
        self.ws = ws
        self.history = history
        self.active = active
        self.pending: deque[Caption] = deque()
        self.pending_bytes = 0
        self.ready = asyncio.Event()
        self.closing = False
        self.close_task: asyncio.Task | None = None

    def enqueue(self, caption: Caption) -> bool:
        if self.closing:
            return False
        if (len(self.pending) >= MAX_PENDING_ITEMS
                or self.pending_bytes + caption.size > MAX_PENDING_BYTES):
            self.closing = True
            self.pending.clear()
            self.pending_bytes = 0
            self.ready.set()
            # At most one close task per client. The reconnect cursor and
            # shared final history make this explicit interim policy recoverable.
            self.close_task = asyncio.create_task(self.ws.close(
                code=1013, reason="Pending limit reached; reconnect to recover"))
            return False
        self.pending.append(caption)
        self.pending_bytes += caption.size
        self.ready.set()
        return True

    async def send(self) -> None:
        for frame in history_frames(self.history):
            if self.closing:
                return
            await self.ws.send(frame)
        self.history = ()
        for caption in self.active:
            if self.closing:
                return
            await self.ws.send(caption.wire)
        self.active = ()
        sent = 0
        while not self.closing:
            if not self.pending:
                self.ready.clear()
                await self.ready.wait()
                continue
            caption = self.pending.popleft()
            self.pending_bytes -= caption.size
            await self.ws.send(caption.wire)
            sent += 1
            if sent % 64 == 0:
                await asyncio.sleep(0)


class LiveRecallServer:
    def __init__(self):
        self.state: SessionState | None = None
        self.source: Any = None
        self.clients: set[ClientSender] = set()

    def session(self, name: Any) -> SessionState:
        if not isinstance(name, str) or not name or len(name) > 128:
            raise ValueError("Expected a nonempty session name")
        try:
            name.encode("utf-8")
        except UnicodeError as error:
            raise ValueError("Session name must be valid UTF-8") from error
        if self.state is None:
            self.state = SessionState(name)
        elif self.state.session != name:
            raise ValueError("This server supports one session at a time")
        return self.state

    async def handle_source(self, ws: Any, state: SessionState) -> None:
        if self.source is not None:
            await ws.close(code=1008, reason="A source is already connected")
            return
        self.source = ws
        print(f"Source connected: {state.session}", flush=True)
        count = 0
        try:
            async for raw in ws:
                message = parse_object(raw)
                if not message or message.get("type") != "CAPTION_UPDATE":
                    continue  # Includes SOURCE_DONE; it never clears state.
                try:
                    caption = state.accept(message)
                except (ValueError, UnicodeError, TypeError):
                    continue
                except OverflowError:
                    await ws.close(code=1013, reason="Active segment capacity exceeded")
                    break
                if caption is None:
                    continue
                for client in tuple(self.clients):
                    if not client.enqueue(caption):
                        self.clients.discard(client)
                count += 1
                if count % 64 == 0:
                    await asyncio.sleep(0)
        finally:
            self.source = None
            print("Source disconnected; session history retained", flush=True)

    async def handle_client(self, ws: Any, state: SessionState,
                            resume: tuple[int, int, float]) -> None:
        segment, revision, seconds = resume
        # No await between snapshot and registration: a source event is either
        # in this immutable snapshot or queued as live work, never lost between.
        history, active = state.snapshot((segment, revision), float(seconds))
        client = ClientSender(ws, history, active)
        self.clients.add(client)

        async def receive_until_closed():
            async for _ in ws:
                pass

        sender = asyncio.create_task(client.send())
        receiver = asyncio.create_task(receive_until_closed())
        try:
            done, _ = await asyncio.wait((sender, receiver),
                                         return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            self.clients.discard(client)
            client.closing = True
            client.ready.set()
            # Close first to unblock any in-flight send, then clean up tasks.
            await ws.close()
            for task in (sender, receiver):
                if not task.done():
                    task.cancel()
            await asyncio.gather(sender, receiver, return_exceptions=True)
            if client.close_task is not None:
                await asyncio.gather(client.close_task, return_exceptions=True)

    async def handler(self, ws: Any) -> None:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            hello = parse_object(raw)
            if not hello or hello.get("type") not in ("SOURCE_HELLO", "CLIENT_HELLO"):
                await ws.close(code=1008, reason="Expected SOURCE_HELLO or CLIENT_HELLO")
                return
            try:
                # Validate the whole hello before its session may bind state.
                resume = (client_resume(hello)
                          if hello["type"] == "CLIENT_HELLO" else None)
                state = self.session(hello.get("session"))
            except ValueError as error:
                await ws.close(code=1008, reason=str(error))
                return
            if resume is None:
                await self.handle_source(ws, state)
            else:
                await self.handle_client(ws, state, resume)
        except asyncio.TimeoutError:
            await ws.close(code=1008, reason="Hello timed out")
        except ConnectionClosed:
            pass

    async def prune_periodically(self) -> None:
        while True:
            await asyncio.sleep(5)
            if self.state is not None:
                self.state.prune()


async def main_async(port: int) -> None:
    server = LiveRecallServer()
    async with websockets.serve(
        server.handler, "0.0.0.0", port,
        max_size=MAX_MESSAGE_BYTES, max_queue=16, write_limit=32 * 1024,
        ping_interval=20, ping_timeout=20, close_timeout=2,
    ):
        print(f"LiveRecall listening on ws://0.0.0.0:{port}", flush=True)
        await server.prune_periodically()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    try:
        asyncio.run(main_async(args.port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
