"""Focused checks that retained state has finite bounds and cannot resurrect.

These complement the WebSocket integration tests. Small temporary capacity
limits and an advancing clock exercise full-capacity and expiry behavior
without allocating huge histories or waiting for a lecture-length interval.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


SERVER = Path(os.environ.get(
    "LIVERECALL_SERVER",
    Path(__file__).resolve().parents[1] / "solution_server.py",
)).resolve()
SPEC = importlib.util.spec_from_file_location("liverecall_server_bounds_test", SERVER)
server = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = server
SPEC.loader.exec_module(server)


class ServerBoundTests(unittest.TestCase):
    def setUp(self):
        self.clock = {"monotonic": 100.0, "epoch": 1000.0}
        mono = patch.object(server.time, "monotonic",
                            side_effect=lambda: self.clock["monotonic"])
        epoch = patch.object(server.time, "time",
                             side_effect=lambda: self.clock["epoch"])
        mono.start()
        epoch.start()
        self.addCleanup(mono.stop)
        self.addCleanup(epoch.stop)
        self.state = server.SessionState("L1")

    def caption(self, segment, *, revision=1, final=True, text="caption"):
        return {
            "type": "CAPTION_UPDATE", "session": "L1", "segment": segment,
            "revision": revision, "source_ts": self.clock["epoch"],
            "final": final, "text": text,
        }

    def snapshot_segments(self):
        finals, active = self.state.snapshot((0, 0), 60)
        return [item.segment for item in finals], [item.segment for item in active]

    def assert_accounting_consistent(self):
        self.assertEqual(self.state.history_bytes,
                         sum(item.size for item in self.state.history))
        self.assertEqual(self.state.active_bytes,
                         sum(item.size for item in self.state.active.values()))
        self.assertEqual(set(self.state.finals),
                         {item.segment for item in self.state.history})

    def test_history_item_limit_evicts_oldest_and_replay_cannot_resurrect_it(self):
        with patch.object(server, "MAX_HISTORY_ITEMS", 3):
            for segment in range(1, 9):
                self.assertIsNotNone(self.state.accept(self.caption(segment)))
                self.assertLessEqual(len(self.state.history), 3)
                self.assertLessEqual(len(self.state.finals), 3)
                self.assert_accounting_consistent()
            self.assertEqual(self.snapshot_segments(), ([6, 7, 8], []))
            self.assertIsNone(self.state.accept(self.caption(1)))
            self.assertEqual(self.snapshot_segments(), ([6, 7, 8], []))

    def test_history_byte_limit_accounts_for_utf8_and_retains_recent_finals(self):
        # Multibyte text catches accounting that accidentally counts characters.
        messages = [self.caption(segment, text="你好" * 60)
                    for segment in range(1, 7)]
        sizes = [server.Caption.from_message(message, "L1").size
                 for message in messages]
        byte_limit = sum(sizes[-2:])
        with patch.object(server, "MAX_HISTORY_BYTES", byte_limit):
            for message in messages:
                self.state.accept(message)
                self.assertLessEqual(self.state.history_bytes, byte_limit)
                self.assert_accounting_consistent()
            self.assertEqual(self.snapshot_segments(), ([5, 6], []))
            self.assertIsNone(self.state.accept(messages[0]))

    def test_expired_history_is_freed_without_losing_retired_segment_guard(self):
        self.state.accept(self.caption(1, revision=4))
        self.clock["monotonic"] += 61
        self.clock["epoch"] += 61
        self.state.prune()
        self.assertEqual(self.snapshot_segments(), ([], []))
        self.assertEqual(len(self.state.history), 0)
        self.assertEqual(len(self.state.finals), 0)
        self.assertEqual(self.state.history_bytes, 0)
        # This replay has a fresh timestamp but an already-completed segment.
        self.assertIsNone(self.state.accept(self.caption(1, revision=4)))
        self.assertIsNotNone(self.state.accept(self.caption(2)))
        self.assertEqual(self.snapshot_segments(), ([2], []))
        self.assert_accounting_consistent()

    def test_active_item_limit_rejects_new_work_without_corrupting_existing_state(self):
        with patch.object(server, "MAX_ACTIVE_ITEMS", 2):
            self.state.accept(self.caption(1, final=False))
            self.state.accept(self.caption(2, final=False))
            with self.assertRaises(OverflowError):
                self.state.accept(self.caption(3, final=False))
            self.assertEqual(self.snapshot_segments(), ([], [1, 2]))
            self.assert_accounting_consistent()
            # Finishing a segment frees capacity; rejected state wasn't admitted.
            self.state.accept(self.caption(1, revision=2))
            self.state.accept(self.caption(3, final=False))
            self.assertEqual(self.snapshot_segments(), ([1], [2, 3]))
            self.assert_accounting_consistent()

    def test_active_byte_limit_rejects_large_revision_then_allows_finalization(self):
        first = self.caption(1, final=False, text="draft")
        initial_size = server.Caption.from_message(first, "L1").size
        with patch.object(server, "MAX_ACTIVE_BYTES", initial_size + 10):
            self.state.accept(first)
            with self.assertRaises(OverflowError):
                self.state.accept(self.caption(1, revision=2, final=False,
                                               text="x" * 1000))
            _, active = self.state.snapshot((0, 0), 60)
            self.assertEqual([(item.segment, item.revision) for item in active], [(1, 1)])
            self.assert_accounting_consistent()
            self.state.accept(self.caption(1, revision=3, text="final text"))
            self.assertEqual(self.snapshot_segments(), ([1], []))
            self.assertEqual(self.state.active_bytes, 0)
            self.assert_accounting_consistent()


if __name__ == "__main__":
    unittest.main()
