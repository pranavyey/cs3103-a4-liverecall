"""Black-box checks for LiveRecall revision and recovery semantics.

Run from the submission root:
    python -m unittest discover -s tests -p 'test_server_core.py' -v

For a scratch copy, set LIVERECALL_SERVER to the absolute server path.
The public instructor harness is deliberately not imported or modified.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

import websockets


SERVER = Path(os.environ.get(
    "LIVERECALL_SERVER",
    Path(__file__).resolve().parents[1] / "solution_server.py",
)).resolve()


def caption(segment: int, revision: int, *, final: bool = True,
            source_ts: float | None = None, **extra) -> dict:
    return {
        "type": "CAPTION_UPDATE",
        "session": "L1",
        "segment": segment,
        "revision": revision,
        "source_ts": time.time() if source_ts is None else source_ts,
        "final": final,
        "text": f"Segment {segment}, revision {revision}.",
        **extra,
    }


class ServerCoreTests(unittest.IsolatedAsyncioTestCase):
    """Each check gets a new real server process and isolated session state."""

    async def asyncSetUp(self):
        self.connections = []
        self.process = None
        self.server_log = None
        self.addAsyncCleanup(self.cleanup_server)
        self.assertTrue(SERVER.is_file(), f"Server not found: {SERVER}")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.uri = f"ws://127.0.0.1:{port}"
        self.server_log = tempfile.TemporaryFile(mode="w+t")
        self.process = subprocess.Popen(
            [sys.executable, "-u", str(SERVER), "--port", str(port)],
            cwd=SERVER.parent,
            stdout=self.server_log,
            stderr=subprocess.STDOUT,
        )
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.server_log.seek(0)
                self.fail(f"Server exited during startup:\n{self.server_log.read()}")
            try:
                probe = await websockets.connect(self.uri, open_timeout=0.3)
                await probe.close()
                return
            except (OSError, TimeoutError):
                await asyncio.sleep(0.03)
        self.fail("Server did not start within eight seconds")

    async def cleanup_server(self):
        for connection in reversed(self.connections):
            with contextlib.suppress(Exception):
                await connection.close()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                await asyncio.to_thread(self.process.wait, timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                await asyncio.to_thread(self.process.wait)
        if self.server_log is not None:
            self.server_log.close()

    async def connection(self):
        ws = await websockets.connect(self.uri, open_timeout=2, close_timeout=1,
                                      max_size=2**20)
        self.connections.append(ws)
        return ws

    async def source(self):
        ws = await self.connection()
        await ws.send(json.dumps({"type": "SOURCE_HELLO", "session": "L1"}))
        return ws

    async def client(self, *, last_segment=0, last_revision=0,
                     history_seconds=60):
        ws = await self.connection()
        await ws.send(json.dumps({
            "type": "CLIENT_HELLO",
            "client_id": len(self.connections),
            "session": "L1",
            "last_segment": last_segment,
            "last_revision": last_revision,
            "history_seconds": history_seconds,
        }))
        history = await self.receive(ws)
        self.assertEqual(history.get("type"), "HISTORY")
        self.assertIsInstance(history.get("items"), list)
        self.assertTrue(all(item["final"] is True for item in history["items"]))
        return ws, history["items"]

    async def receive(self, ws, timeout=2):
        raw = await asyncio.wait_for(ws.recv(), timeout)
        msg = json.loads(raw)
        self.assertIsInstance(msg, dict)
        return msg

    async def send(self, source, *messages):
        for message in messages:
            await source.send(json.dumps(message))

    async def send_observed(self, source, observer, message):
        """A received live message proves the source update was processed."""
        await self.send(source, message)
        received = await self.receive(observer)
        self.assertEqual(received["type"], "CAPTION_UPDATE")
        self.assertEqual(received["segment"], message["segment"])
        self.assertEqual(received["revision"], message["revision"])
        self.assertEqual(received["final"], message["final"])
        return received

    async def through_final(self, client, last_segment):
        """Read through an ordered marker instead of relying on silence timeouts."""
        updates = []
        for _ in range(last_segment * 20 + 20):
            message = await self.receive(client)
            self.assertEqual(message["type"], "CAPTION_UPDATE")
            updates.append(message)
            if message["segment"] == last_segment and message["final"]:
                return updates
        self.fail("Final marker never arrived")

    async def test_full_revision_stream_and_variable_revision_counts(self):
        viewer, history = await self.client()
        self.assertEqual(history, [])
        source = await self.source()
        messages = [
            caption(1, 1, final=False),
            caption(1, 2, final=False),
            caption(1, 4, final=False),
            caption(1, 7),
            caption(2, 1),
        ]
        await self.send(source, *messages)
        received = await self.through_final(viewer, 2)
        self.assertEqual(
            [(m["segment"], m["revision"], m["final"]) for m in received],
            [(m["segment"], m["revision"], m["final"]) for m in messages],
            "Normal operation must preserve all distinct revisions",
        )

    async def test_stale_duplicate_and_pre_final_revisions_are_suppressed(self):
        viewer, _ = await self.client()
        source = await self.source()
        await self.send(source,
            caption(1, 1, final=False),
            caption(1, 3, final=False),
            caption(1, 2, final=False),  # stale while active
            caption(1, 3, final=False),  # duplicate while active
            caption(1, 7),
            caption(1, 6, final=False),  # stale after completion
            caption(1, 7),              # duplicate final
            caption(2, 1),             # processing marker
        )
        received = await self.through_final(viewer, 2)
        self.assertEqual(
            [(m["segment"], m["revision"]) for m in received],
            [(1, 1), (1, 3), (1, 7), (2, 1)],
        )
        _, history = await self.client()
        self.assertEqual([(m["segment"], m["revision"]) for m in history],
                         [(1, 7), (2, 1)])

    async def test_history_is_ordered_final_only_and_excludes_resume_cursor(self):
        observer, _ = await self.client()
        source = await self.source()
        for item in [caption(1, 2), caption(2, 5), caption(3, 9, final=False)]:
            await self.send_observed(source, observer, item)

        _, history = await self.client(last_segment=1, last_revision=2)
        self.assertEqual([(m["segment"], m["revision"]) for m in history], [(2, 5)])
        _, acknowledged = await self.client(last_segment=2, last_revision=5)
        self.assertEqual(acknowledged, [])
        _, newer_same_segment = await self.client(last_segment=2, last_revision=4)
        self.assertEqual([(m["segment"], m["revision"]) for m in newer_same_segment],
                         [(2, 5)])

    async def test_late_join_receives_latest_active_state_then_live_revisions(self):
        observer, _ = await self.client()
        source = await self.source()
        for item in [caption(1, 2), caption(2, 1, final=False),
                     caption(2, 4, final=False)]:
            await self.send_observed(source, observer, item)
        late, history = await self.client()
        self.assertEqual([item["segment"] for item in history], [1])
        active = await self.receive(late)
        self.assertEqual((active["type"], active["segment"], active["revision"], active["final"]),
                         ("CAPTION_UPDATE", 2, 4, False))
        await self.send(source, caption(2, 9))
        final = await self.receive(late)
        self.assertEqual((final["segment"], final["revision"], final["final"]), (2, 9, True))

    async def test_disconnect_recovers_exact_missing_finals_and_continues_live(self):
        observer, _ = await self.client()
        viewer, _ = await self.client()
        source = await self.source()
        await self.send_observed(source, observer, caption(1, 3))
        self.assertEqual((await self.receive(viewer))["segment"], 1)
        await viewer.close()

        for segment in (2, 3, 4):
            await self.send_observed(source, observer, caption(segment, segment + 2))
        reconnected, history = await self.client(last_segment=1, last_revision=3)
        self.assertEqual([m["segment"] for m in history], [2, 3, 4])
        await self.send(source, caption(5, 1))
        live = await self.receive(reconnected)
        self.assertEqual((live["type"], live["segment"]), ("CAPTION_UPDATE", 5))

    async def test_source_reconnect_preserves_session_history(self):
        observer, _ = await self.client()
        source = await self.source()
        await self.send_observed(source, observer, caption(1, 4))
        await source.close()
        source_again = await self.source()
        await self.send_observed(source_again, observer, caption(2, 6))
        _, history = await self.client()
        self.assertEqual([m["segment"] for m in history], [1, 2])

    async def test_history_and_concurrent_live_delivery_have_no_gap_or_duplicate(self):
        observer, _ = await self.client()
        source = await self.source()
        for segment in range(1, 9):
            await self.send_observed(source, observer, caption(segment, 1))

        late = await self.connection()
        await late.send(json.dumps({
            "type": "CLIENT_HELLO", "client_id": 777, "session": "L1",
            "last_segment": 0, "last_revision": 0, "history_seconds": 60,
        }))
        burst = asyncio.create_task(self.send(
            source, *(caption(segment, 1) for segment in range(9, 101))))
        first = await self.receive(late)
        self.assertEqual(first["type"], "HISTORY")
        self.assertTrue(all(m["final"] is True for m in first["items"]))
        seen = [m["segment"] for m in first["items"]]
        while not seen or seen[-1] != 100:
            update = await self.receive(late)
            self.assertEqual(update["type"], "CAPTION_UPDATE")
            self.assertTrue(update["final"])
            seen.append(update["segment"])
            self.assertLessEqual(len(seen), 100, "Duplicate final delivered during handoff")
        await burst
        self.assertEqual(seen, list(range(1, 101)))

    async def test_history_window_filters_by_source_event_time(self):
        """Uses large margins so scheduler jitter cannot affect window membership."""
        observer, _ = await self.client()
        source = await self.source()
        now = time.time()
        for segment, age in enumerate((70, 40, 20, 5), start=1):
            await self.send_observed(source, observer, caption(segment, 1, source_ts=now-age))
        _, sixty = await self.client(history_seconds=60)
        _, thirty = await self.client(history_seconds=30)
        _, zero = await self.client(history_seconds=0)
        self.assertEqual([m["segment"] for m in sixty], [2, 3, 4])
        self.assertEqual([m["segment"] for m in thirty], [3, 4])
        self.assertEqual(zero, [])
        # Retiring old history must not let a duplicate final become new state.
        await self.send(source, caption(1, 1), caption(5, 1))
        after_retirement = await self.through_final(observer, 5)
        self.assertEqual([m["segment"] for m in after_retirement], [5])

    async def test_large_history_fits_client_message_limit_without_missing_finals(self):
        observer, _ = await self.client()
        source = await self.source()
        for segment in range(1, 17):
            await self.send_observed(source, observer,
                                     caption(segment, 1, text="x" * 70_000))
        # The total recovery payload exceeds the supplied client's 1MiB limit.
        # Splitting it into ordered HISTORY messages is an allowed extension.
        late, initial = await self.client()
        seen = [m["segment"] for m in initial]
        await self.send(source, caption(17, 1))
        while not seen or seen[-1] != 17:
            message = await self.receive(late)
            if message["type"] == "HISTORY":
                self.assertTrue(all(m["final"] is True for m in message["items"]))
                seen.extend(m["segment"] for m in message["items"])
            else:
                self.assertEqual(message["type"], "CAPTION_UPDATE")
                self.assertTrue(message["final"])
                seen.append(message["segment"])
            self.assertLessEqual(len(seen), 17)
        self.assertEqual(seen, list(range(1, 18)))

    async def test_unknown_fields_and_control_messages_do_not_break_delivery(self):
        viewer, _ = await self.client()
        source = await self.source()
        await self.send(source,
            caption(1, 1, instructor_phase="opaque", arbitrary={"nested": [1, 2]}),
            {"type": "SOURCE_DONE", "session": "L1", "extra": True},
            {"type": "FUTURE_SOURCE_CONTROL", "session": "L1"},
            caption(2, 1),
        )
        received = await self.through_final(viewer, 2)
        self.assertEqual([m["segment"] for m in received], [1, 2])

    async def test_invalid_hello_does_not_crash_server(self):
        for malformed in ("[", "[]", "null", '{"type":"NOT_A_HELLO"}'):
            bad = await self.connection()
            await bad.send(malformed)
            await bad.close()
        viewer, _ = await self.client()
        source = await self.source()
        await self.send(source, caption(1, 1))
        self.assertEqual((await self.receive(viewer))["segment"], 1)
        self.assertIsNone(self.process.poll())

    async def test_invalid_resume_hello_does_not_bind_the_session(self):
        bad = await self.connection()
        await bad.send(json.dumps({
            "type": "CLIENT_HELLO", "client_id": 999, "session": "BAD",
            "last_segment": -1, "last_revision": 0, "history_seconds": 60,
        }))
        with self.assertRaises(websockets.exceptions.ConnectionClosed):
            await asyncio.wait_for(bad.recv(), 2)
        # Rejecting that malformed request must not prevent a valid L1 lecture.
        viewer, history = await self.client()
        self.assertEqual(history, [])
        source = await self.source()
        await self.send(source, caption(1, 1))
        self.assertEqual((await self.receive(viewer))["segment"], 1)

    async def test_invalid_source_session_cannot_bind_state_or_hold_source_lease(self):
        bad = await self.connection()
        await bad.send(json.dumps({"type": "SOURCE_HELLO", "session": "\ud800"}))
        with self.assertRaises(websockets.exceptions.ConnectionClosed):
            await asyncio.wait_for(bad.recv(), 2)
        viewer, history = await self.client()
        self.assertEqual(history, [])
        source = await self.source()
        await self.send(source, caption(1, 1))
        self.assertEqual((await self.receive(viewer))["segment"], 1)

    async def test_malformed_captions_cannot_poison_later_valid_state(self):
        viewer, _ = await self.client()
        invalid_messages = [
            caption(True, 1),       # bool must not be treated as integer 1
            caption(1, True),
            caption(0, 1),
            caption(1, 0),
            caption(1, 1, final="false"),
            caption(1, 1, source_ts=float("nan")),
            {**caption(1, 1), "text": ["not", "a string"]},
            {"type": "CAPTION_UPDATE", "session": "L1"},
        ]
        for invalid in invalid_messages:
            source = await self.source()
            await self.send(source, invalid)
            # Either ignoring invalid data or closing its connection is safe.
            await source.close()
        valid_source = await self.source()
        valid = caption(1, 1)
        await self.send(valid_source, valid)
        received = await self.receive(viewer)
        self.assertEqual(received["segment"], 1)
        self.assertEqual(type(received["segment"]), int)
        self.assertEqual(type(received["revision"]), int)
        self.assertIs(received["final"], True)
        self.assertEqual(received["text"], valid["text"])
        self.assertEqual(received["source_ts"], valid["source_ts"])
        self.assertIsNone(self.process.poll())


if __name__ == "__main__":
    unittest.main()
