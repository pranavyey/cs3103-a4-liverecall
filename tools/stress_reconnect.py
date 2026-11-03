"""Gate 5 stress check: repeated reconnects and reconnect storms.

The public harness disconnects each client at most once. This script makes
every client disconnect and reconnect many times, resuming from the highest
final it holds, and checks that each client ends with every final exactly
once (no gaps, no duplicates, no stale revisions). It starts its own server
and the unmodified caption_source.py; it does not change any public file.

  python tools/stress_reconnect.py --clients 50 --segments 60
  python tools/stress_reconnect.py --clients 100 --segments 60 --storm
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import socket
import subprocess
import sys
import time
from pathlib import Path

import websockets

ROOT = Path(__file__).resolve().parents[1]


class Viewer:
    def __init__(self, cid: int):
        self.cid = cid
        self.finals: dict[int, int] = {}      # segment -> final revision
        self.latest: dict[int, int] = {}      # segment -> newest revision seen
        self.duplicates = 0
        self.stale = 0
        self.reconnects = 0
        self.recovered = 0
        self.recovery_ms: list[float] = []

    def cursor(self) -> tuple[int, int]:
        if not self.finals:
            return 0, 0
        seg = max(self.finals)
        return seg, self.finals[seg]

    def apply(self, item: dict, recovered: bool) -> None:
        seg, rev = item.get("segment"), item.get("revision")
        if not isinstance(seg, int) or not isinstance(rev, int):
            return
        # Same classification as load_clients.py: an already-seen revision
        # (provisional or final) is a duplicate, an older one is stale.
        previous = self.latest.get(seg)
        if previous is not None and rev < previous:
            self.stale += 1
            return
        if previous is not None and rev == previous:
            self.duplicates += 1
            return
        self.latest[seg] = rev
        if item.get("final"):
            self.finals[seg] = rev
            self.recovered += recovered

    async def session(self, uri: str, stay: float) -> None:
        seg, rev = self.cursor()
        try:
            async with websockets.connect(uri, max_size=2**20, open_timeout=5,
                                          close_timeout=1) as ws:
                started = time.monotonic()
                await ws.send(json.dumps({
                    "type": "CLIENT_HELLO", "client_id": self.cid, "session": "L1",
                    "last_segment": seg, "last_revision": rev,
                    "history_seconds": 60,
                }))
                end = started + stay
                while (left := end - time.monotonic()) > 0:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), left)
                    except asyncio.TimeoutError:
                        break
                    msg = json.loads(raw)
                    if msg.get("type") == "HISTORY":
                        for item in msg.get("items", []):
                            self.apply(item, True)
                        if self.reconnects:
                            self.recovery_ms.append((time.monotonic() - started) * 1000)
                    else:
                        self.apply(msg, False)
                # Leaving the context closes the socket: an abrupt disconnect.
        except (OSError, websockets.exceptions.WebSocketException):
            pass
        self.reconnects += 1


async def run_viewer(v: Viewer, uri: str, stop: asyncio.Event, storm_tick,
                     rng: random.Random) -> None:
    while not stop.is_set():
        if storm_tick is None:
            await v.session(uri, rng.uniform(2, 5))
            if stop.is_set():
                break
            await asyncio.sleep(rng.uniform(0.5, 3))
        else:
            # Storm: every client drops and reconnects at the same instants.
            await storm_tick.wait()
            await v.session(uri, 3.5)
    # Final settle: stay connected long enough to collect what is left.
    await v.session(uri, 4)


def wait_for_port(port: int) -> None:
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return
        except OSError:
            time.sleep(0.15)
    raise RuntimeError("server did not start")


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--clients", type=int, default=50)
    p.add_argument("--segments", type=int, default=60)
    p.add_argument("--port", type=int, default=8771)
    p.add_argument("--storm", action="store_true",
                   help="all clients disconnect/reconnect together every 4 s")
    p.add_argument("--seed", type=int, default=3103)
    args = p.parse_args()
    uri = f"ws://127.0.0.1:{args.port}"
    log = open(ROOT / "stress_reconnect_server.log", "w")
    server = subprocess.Popen([sys.executable, "-u", "solution_server.py",
                               "--port", str(args.port)], cwd=ROOT,
                              stdout=log, stderr=subprocess.STDOUT)
    try:
        wait_for_port(args.port)
        rng = random.Random(args.seed)
        viewers = [Viewer(i) for i in range(args.clients)]
        stop = asyncio.Event()
        tick = asyncio.Event() if args.storm else None
        tasks = [asyncio.create_task(run_viewer(v, uri, stop, tick,
                                                random.Random(rng.random())))
                 for v in viewers]

        async def storm():
            while not stop.is_set():
                tick.set()
                await asyncio.sleep(0.05)
                tick.clear()
                await asyncio.sleep(3.95)

        storm_task = asyncio.create_task(storm()) if args.storm else None
        await asyncio.sleep(1)
        source = await asyncio.create_subprocess_exec(
            sys.executable, "-u", "caption_source.py", "--uri", uri,
            "--segments", str(args.segments), "--quiet", cwd=ROOT)
        rc = await source.wait()
        stop.set()
        if tick is not None:
            tick.set()
        await asyncio.gather(*tasks)
        if storm_task:
            storm_task.cancel()
        if rc != 0:
            print("caption_source.py failed", file=sys.stderr)
            return 1
    finally:
        server.terminate()
        server.wait(5)
        log.close()

    expected = set(range(1, args.segments + 1))
    complete = sum(1 for v in viewers if set(v.finals) == expected)
    got = sum(len(set(v.finals) & expected) for v in viewers)
    dup = sum(v.duplicates for v in viewers)
    stale = sum(v.stale for v in viewers)
    recon = sum(v.reconnects for v in viewers)
    recovered = sum(v.recovered for v in viewers)
    rec = sorted(ms for v in viewers for ms in v.recovery_ms)
    p95 = rec[int(0.95 * (len(rec) - 1))] if rec else 0.0
    mode = "storm (all together every 4 s)" if args.storm else "random (2-5 s on, 0.5-3 s off)"
    print(f"Mode: {mode}; clients={args.clients}; segments={args.segments}")
    print(f"Sessions (connects):           {recon}")
    print(f"Finals recovered via HISTORY:  {recovered}")
    print(f"HISTORY arrival P95:           {p95:.1f} ms")
    print(f"Clients with every final:      {complete}/{args.clients}")
    print(f"Final completeness:            {100 * got / (args.segments * args.clients):.2f}%")
    print(f"Duplicate revisions:           {dup}")
    print(f"Stale revisions:               {stale}")
    print("Server log: stress_reconnect_server.log")
    return 0 if complete == args.clients and dup == 0 and stale == 0 else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
