# Report dump (raw material for report.pdf)

Working notes to draft the 4 to 5 page report from. Not a submission file: leave it out of the final package. Every number below says where it came from. **Dev** means one run, for development only. Report numbers must be official: the median of 3 runs on the Ubuntu VM, on a tagged commit (still to do, Gate 6).

Required report contents (spec, section 11): architecture and protocol; revision/recovery semantics; backpressure/overload policy; public experiments; at least one before/after optimization comparison; P50/P95/P99/freshness/final-completeness results; discussion of failures and trade-offs; limitations; and a short future-work/FYP direction. Length: 4 to 5 pages, excluding references and appendices.

---

## 1. Architecture and protocol

- **One process, one asyncio event loop** (`solution_server.py`, websockets 16.1.1, Python 3.12). Start command: `python solution_server.py --port 8765`.
- **Roles:** one source connection (SOURCE_HELLO, CAPTION_UPDATE, SOURCE_DONE) and many viewer clients (CLIENT_HELLO with last_segment, last_revision, history_seconds).
- **Shared session state (`SessionState`):**
  - Recent final history, bounded (see section 3).
  - The latest revision of each active (not yet final) segment.
  - A `highest_segment_seen` high-water mark, so an evicted or retired segment can't come back.
- **Per-client sender (`ClientSender`):** each client has its own bounded queue and a single sender task. That task sends recovery and live updates in order, so a slow client never blocks the source or other clients.
- **Serialisation once:** each caption is serialised to JSON once, and every client is sent the same string.
- **Large HISTORY is split** into ordered frames that fit the client's 1 MiB message limit. No finals are lost by splitting (test: `test_large_history_fits_client_message_limit_without_missing_finals`).
- **Input validation:**
  - Caption fields are checked; malformed captions can't corrupt later state.
  - Session names are checked, including UTF-8 validity.
  - The whole resume request is checked before the session is bound (see AI_USAGE correction 1).
- **Browser client (Gate 3, 30106e2):**
  - Keeps one entry per segment and replaces it in place when a newer revision arrives. Provisionals show as amber italic with their revision number; finals as black with a "final" tag.
  - Keeps finals locally for 90 s (at most 2000), so the 15/30/60 s recall works without asking the server.
  - Its resume cursor is the highest final it holds, never a provisional.
  - Reconnects automatically with backoff from 0.5 to 5 s and a countdown. Every hello asks for 60 s of history, so a late joiner has a full 60 s view straight away.
  - Has a "Simulate disconnect" button for the demo.
- Diagram idea: source → SessionState → N ClientSenders (each with a queue) → WebSocket clients. Show the history and active stores, plus the ping/pong path used for slow-client detection.

## 2. Revision and recovery semantics

- **Revisions:** only higher revisions of an active segment are accepted. Duplicates and older revisions are dropped. A final is immutable: anything that arrives for a segment after its final is ignored.
- **Recovery:** on reconnect, the server sends finals newer than the client's (last_segment, last_revision) cursor, oldest first. It never sends finals the client already reported. It then sends the latest state of active segments, then live updates.
- **No-gap handoff:** the history/active snapshot is taken and the client is registered with **no `await` in between**.
  - An await between them would let a final miss both the snapshot and live delivery, a permanent gap.
  - Registering first and taking the snapshot later would cause duplicates instead.
  - The student explained both in the Gate 2 viva notes.
- **History window (course clarification, 79c9720):**
  - A client may request up to 60 s of history. Requests over 60 s are served up to 60 s instead of being rejected; negative values are still rejected.
  - Finals are retained for **70 s** internally, a margin for timing jitter at the boundary.
  - Server-initiated resyncs use the full 70 s.
- **Evidence:**
  - Gate 2 matched reconnect check, 55 segments: every client received 55/55 finals. The starter's reconnecting clients received 49/55, because the starter sends an empty HISTORY (experiments/server-core/).
  - Dev T4 runs had 100% completeness, 120 recovered items, 0 duplicate or stale, and recovery P95 of 7.4 ms in the cloud container.

## 3. Backpressure and overload policy

- **Bounds (fixed, independent of lecture length and client delay):**
  - History: 70 s, and also at most 32,768 items and 32 MiB.
  - Active segments: at most 128 items and 4 MiB.
  - Per-client pending queue: soft limit 32 items or 256 KiB, hard limit 256 items or 2 MiB.
- **Coalescing:** a client counts as behind when its oldest queued item is older than 0.5 s, or it has more than 32 queued items. Its queue is then compacted: provisionals that a newer queued revision of the same segment has replaced are dropped. Finals and the newest revision of each segment are kept, in order.
- **Hard bound:** if the queue is still over the hard limit, it is cleared and the client is **resynchronised from shared history**, starting after the last final it was sent. It is not disconnected, and finals aren't lost (within the retention window).
- **Hidden backlog finding (Gate 4):** TCP buffers and the client library's 16-message queue hid slow readers, so the server never saw a backlog.
  - **Ping send window:** a ping is sent every 2 messages, with at most 2 unanswered. The server waits for pongs, which keeps the backlog in the server's queue, where obsolete revisions can still be dropped.
- **Slow mode (finals only):** once a client is detected as slow, it gets finals only for 15 s. The hold doubles each time it trips again, up to 120 s. Its newest provisional stays queued and is sent when the hold ends.
- **Slow-mode trigger: four versions, all measured (main engineering story, see section 6):**
  1. One pong later than 1 s marks the client slow.
  2. Two consecutive late pongs are needed (bb50641). VM T5: 19 of 100 normal clients wrongly tripped.
  3. Late pongs must prove 3 s without reading, timed from when the ping was **sent** (`now − latency`). The first attempt at this (2c0f320) timed from pong arrival and broke T3. The fix (d3142fa) brought T5 false trips down to 1.
  4. **Final (405da57):** the streak is measured only **up to the latest late pong**. Fast pongs neither start nor end a streak; 1 s with no late pong ends it.
- **Why this matches the course clarification:**
  - Finals are never dropped to make room for provisionals.
  - The newest revision of each active segment is kept.
  - There is no unbounded queue, and no backlog that is only drained after the source stops.
  - A 500 ms reader can keep up with finals alone (about 1 per 0.75 s), so slow mode delivers finals during the lecture.
- **Slow-reader lag floor:** about 5 to 6 s at P50 for a 500 ms reader. This sits in the client library's 16-message buffer, which the server can't see into (16 × 0.5 s ≈ 8 s). Accepted, and explained in DESIGN_NOTES Gate 4.

## 4. Public experiments (to fill with official runs)

Required: T1 to T5, each run at least 3 times, reporting the median, using the unmodified harness. Commands from the spec:
```
python run_demo.py --clients 20 --duration 20 --runs 3                                    # T1
python run_demo.py --clients 100 --duration 40 --runs 3                                   # T2
python run_demo.py --clients 100 --duration 60 --runs 3 --slow-percent 10 --slow-ms 500   # T3
python run_demo.py --clients 100 --duration 60 --runs 3 --disconnect-percent 20 --disconnect-at 15 --disconnect-seconds 5  # T4
sudo ./network_profiles/delay_loss.sh lo; python run_demo.py --clients 100 --duration 40 --runs 3 --output-stem t5; sudo ./network_profiles/reset.sh lo  # T5
```
- **Environment:** Multipass VM liverecall-a4, Ubuntu 24.04.5 LTS, ARM64, 2 CPUs, 4 GB RAM, Python 3.12.3, websockets 16.1.1. Host: Mac. The other VM (mininet-lab) was running; host activity was not controlled.
- **Supplemental runs:** add runs with `--source-segments` (see limitation 1), so completeness reflects the server and not the cutoff. Label them as supplemental.
- **Metrics to report:**
  - P50, P95 and P99 caption age.
  - Fresh caption ratio and fresh final ratio (500 ms).
  - Final completeness.
  - Normal update coverage.
  - Recovery P95 for T4.
  - Normal and slow clients separately for T3.
  - Duplicate and stale counts.
  - SLOW_MODE_ENTER counts from the server log (as an extra column).
- **Results table, official (TODO, Gate 6, tagged commit):**

| Test | Completeness | P50 | P95 | P99 | Fresh | Fresh final | Coverage | Dup/stale | Notes |
|---|---|---|---|---|---|---|---|---|---|
| T1 | | | | | | | | | |
| T2 | | | | | | | | | |
| T3 normal / slow | | | | | | | | | |
| T4 | | | | | | | | | recovery P95 |
| T5 delay_loss | | | | | | | | | |
| T5 2 Mbit (extra) | | | | | | | | | |

**Dev results so far (VM, one run each, for the narrative only):**

| Run | Commit | Result |
|---|---|---|
| T5 delay_loss, 100 clients, 40 s | bb50641 | 100% finals, P50/P95/P99 263/741/1087 ms, fresh 86.4%, coverage 97.71%, 0/0 |
| T5 delay_loss | e6fceec | 99.98%, P95 802 ms, coverage 95.50%, **19/100 normal clients in slow mode** (pongs 1.0 to 1.4 s, one 2.2 s) |
| T5 delay_loss | d3142fa | 100%, P95 726 ms, coverage 99.66%, 1 trip (its pong was 463 ms, the edge case fixed later) |
| T5 delay_loss | 405da57 | 99.98%, P95 752 ms, coverage 99.41%, 1 trip from a genuine 4.0 s pong |
| T5 2 Mbit, 49 segments | 405da57 | 89.80%: every client got 44/49, a capture cutoff |
| T5 2 Mbit, `--source-segments 40` | 405da57 | **100% completeness, 100% coverage**, 0 slow-mode entries |
| T4, 100 clients, 20% disconnect, `--source-segments 40` | 79c9720 | **100%**, 120 recovered items, 0/0, 0 connection errors; 21 tests OK on the VM |
| Repeated reconnects (tools/stress_reconnect.py), 100 clients x 60 segments | b1961d3 | random: 1111 connects, 2023 finals recovered, HISTORY P95 2.9 ms; storm (all every 4 s): 1500 connects, HISTORY P95 16.1 ms; **both 100/100 complete, 0/0**, no resyncs. Starter on the same script (Mac, 30x25): 0/30 complete, 67.87% |
| T3 prescribed (60 s) | 405da57 vs bb50641 | 88.42% vs 89.82%; both cut off; normal P95 20 ms, 100% fresh; slow P50 6.4 s; all 10 slow readers caught at late_for=6.0 s |

## 5. Before/after comparison (required)

- **Before:** the starter (tag starter-baseline, 80d08b8). Measured on the VM; medians of 3 in experiments/baseline/.
  - T3: completeness 82.89%, slow-reader P95 24.8 s, normal P95 17.3 ms, P99 21.5 s.
  - T4: completeness 83.95%, 0 recovered history items (the starter sends an empty HISTORY).
  - Supplemental T4, 55 segments: 97.82%, 0 recovered.
- **After:** the final tagged commit, with the **same parameters** (TODO). Dev indications:
  - Cloud container T3: 99.7 to 99.8% completeness, slow P95 down from 24.8 s.
  - T4: 100%, 120 recovered items.
- **Second comparison, a single optimization disabled:**
  - Coalescing plus the ping window (fbcb49f) against the bounded FIFO alone, one T3 run in the dev container: completeness 95.1% → 99.7%, slow P99 24.0 s → 8.1 s, normal P95 under 14 ms both times.
  - The slow-mode trigger versions on T5 (19 → 1 → 1 false trips; coverage 95.50% → 99.66% → 99.41%).
- **Trade-off:** slow readers get fewer provisional revisions (finals only while in slow mode). In return, normal clients stay fresh and finals stay complete. Normal update coverage is the measure that shows normal clients don't lose provisionals.

## 6. Failures and trade-offs (discussion material)

- **Slow-mode trigger iterations** (section 3). This is the main "engineering evidence" story: every change was driven by a measurement.
  - On a lossy link, **head-of-line blocking** makes several pongs late together: data behind a lost segment waits for the retransmission, whose wait doubles each time it is lost again (0.2, 0.4, 0.8 s…).
  - **Slow-reader pong trace** (Mac):
    - fast pongs for about 8 s while the TCP buffer and the library queue absorb the backlog;
    - then about 5.5 s of silence once the library stops reading the socket;
    - then two late pongs at the same instant;
    - then a burst of fast pongs.
  - **Why time from when the ping was sent:** a pong with latency L proves at least L seconds without reading.
  - **Why only up to the latest late pong:** time passing after it proves nothing. Counting it let a 2.2 s pong plus a fast pong 0.9 s later count as 3.1 s and trip slow mode.
  - **Why not just raise the threshold to 2.5 s:** a fixed cutoff on one pong can't tell "stopped reading" from an unlucky retransmission. Because retransmission waits double, a harsher link crosses any fixed value.
- **Remaining T5 trip:** one normal client returned a single 4.0 s pong, so it really went 4 s without reading. Under the rule's definition that is unresponsive, and the cost is 15 s of finals only for that client. Accepted.
- **T5 effect on latency (spec asks to explain):**
  - WebSocket runs over TCP, so the 3% loss shows up as retransmission and head-of-line delay, not missing messages. Finals stayed at about 100%.
  - The ~120 ms delay applies in both directions on loopback, giving a base round trip of about 240 ms. With retransmissions, P50 is about 260 ms and P95/P99 about 750 / 1060 ms.
  - Fresh ratio falls to about 87%.
- **Rejected shortcut:** sending live finals to slow clients labelled as HISTORY, which the load client handles without its simulated slow-reader delay. It would have improved the number by exploiting the measurement, and it misuses what HISTORY means in the protocol. The student stopped it (AI_USAGE).
- **Ping overhead:** a ping every 2 messages costs extra frames and CPU. It's the price of seeing the backlog. Measured: the source's timing was the same with 1 and 100 clients, so it doesn't slow the source.

## 7. Limitations

1. **VM capture cutoff (environment):**
   - On liverecall-a4, the source takes about 70 s for 76 segments: about 0.905 s each instead of the 0.75 s `run_demo.py` assumes.
   - Measured: each `asyncio.sleep(0.2)` takes 0.2517 s (51.7 ms over, 3 waits per segment). This happens even with **1 client on an idle VM** (84.21% completeness).
   - Results are written at about 60.4 s, before SOURCE_DONE, so the last segments are never captured, whatever the server does. The starter's T1 had 95.45% for the same reason.
   - Not caused by server load, and the harness can't be changed. Report the prescribed runs as measured, with supplemental runs alongside. (TODO: ask course staff whether the grading machine keeps 0.75 s timing.)
2. **Slow-reader lag floor:** about 5 to 6 s at P50, because of the client library's 16-message buffer, which the server can't see.
3. **Detection delay:** a slow reader is only detected after about 8 s, once its buffers fill.
4. **Retention:** recovery is guaranteed for 60 s only. A client away longer gets at most 60 s (70 s on a server resync).
5. **Single process, single core:** no horizontal scaling. One session per server instance.
6. **Results are from one VM** with uncontrolled host activity.

## 8. Future work / FYP direction (short)

- An adaptive slow-mode threshold based on each client's own round-trip time; QUIC/HTTP3 or WebTransport to avoid head-of-line blocking across streams.
- Have the server measure clients' reading speed directly (application-level acknowledgements) instead of inferring it from ping timing.
- Fan-out across processes or machines (pub/sub), several sessions, and persistent history.
- Optional: plug in live ASR (bonus_asr/) as the caption source.

## 9. Pointers for the appendix and the viva

- **Commits:**
  - starter-baseline 80d08b8; server-core-tested 36ed410; browser client 30106e2.
  - Slow-client isolation fbcb49f; slow-mode trigger bb50641 → 2c0f320 → d3142fa → 405da57.
  - Slow-mode logging e6fceec; history cap 79c9720.
  - Final tag: TODO.
- **Evidence folders:**
  - experiments/baseline/, experiments/server-core/, experiments/mac-local/ (untracked, dev only).
  - VM: ~/lr-* folders with the t3_*/t5_* logs. TODO: copy the official run folders back into experiments/.
- **Docs:** DESIGN_NOTES.md (per-gate design and student explanations), AI_USAGE.md (tools, one useful suggestion, and the corrections and rejected suggestions), EXECUTION_STATUS.md (timeline).
- **Server log lines** to quote: `SLOW_MODE_ENTER client=… hold=… pong=… late_for=…` and `CLIENT_STATS client=… coalesced=… slow_trips=… resyncs=…`.
- **Tests:** 21 (tests/test_server_core.py integration tests, tests/test_server_bounds.py bounded-state tests); tests/browser_e2e.js (2 tabs plus a late joiner in headless Chromium).
