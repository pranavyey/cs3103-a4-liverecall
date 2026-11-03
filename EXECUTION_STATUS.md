# LiveRecall execution status

Live tracker that sits next to EXECUTION_PLAN.md. Any agent or session picking up the work reads this first and updates it at each gate: what passed, the commit, open defects, and the next task. Times are Singapore time.

**Last updated:** Tue 3 Nov 2026, 20:45, by Claude (chat session with Pranav)
**Branch:** work/implementation, tracking origin/work/implementation. main is not advanced yet.
**Current plan block:** Tue 20:30 to 22:30 (bounded sending, slow-client isolation). About 2.5 h ahead of schedule.

## Gates

| Gate | Plan block | State | Commit | Evidence |
|---|---|---|---|---|
| 1. Environment and baseline | Tue 14:30 to 15:30 | Done | cc8e6b7, 8d77709 | experiments/baseline/ (starter T1, T3, T4 on Ubuntu VM) |
| 2. Server revisions, history, late join, recovery | Tue 15:30 to 18:30 | Done | 36ed410 (tag server-core-tested) | experiments/server-core/, tests/test_server_core.py |
| 3. Browser client | Tue 18:30 to 20:30 | Done | 30106e2 | tests/browser_e2e.js (2 tabs + late joiner, no gaps or duplicates) |
| 4. Bounded sending, slow-client isolation | Tue 20:30 to 22:30 | Design done; T5 check outstanding | fbcb49f, plus the late-pong change (see log) | One-run dev checks only (see below) |
| 5. Stress, recovery, bandwidth, long runs | Tue 22:30 to Wed 00:30 | Not started | | |
| 6. Required T1 to T5 on Ubuntu, 3 runs each | Wed 00:30 to 03:00, 09:00 to 11:00 | Not started | | |
| 7. Report and docs | Wed 11:00 to 14:00 | Not started; DESIGN_NOTES.md is kept per gate | | |
| 8. Demo video | Wed 14:00 to 16:00 | Not started | | |
| 9. Clean-package test, release, upload | Wed 16:00 to 20:00 | Not started | | |

Student explanations recorded in DESIGN_NOTES.md: Gates 2, 3 and 4 done.

## Latest results (dev checks, one run each, not report evidence)

| Test | Where | Completeness | Normal P95 | Slow P50 | Dup/stale | Notes |
|---|---|---|---|---|---|---|
| T1 20 clients 20 s | Mac | 100% | 5.4 ms | | 0/0 | experiments/mac-local/ |
| T2 100 clients 40 s, 3 runs | Mac | 100% all runs | 14 to 20 ms | | 0/0 | experiments/mac-local/ |
| T3 100 clients, 10% slow 500 ms | Cloud dev container | 99.7 to 99.8% | 14 to 15 ms | 5.6 to 5.7 s | 0/0 | Starter: 82.9%, slow P95 24.8 s |
| T4 100 clients, 20% disconnect | Cloud dev container | 100% | 15.6 ms | | 0/0 | 120 recovered items, recovery P95 7.4 ms |
| 20 clients, 30% slow, 20 s | Mac | 87.7% | 4.9 ms | 4.7 s | 0/0 | Short run: slow clients' last finals arrive after capture ends |
| T5 run 3, same profile | Ubuntu VM, d3142fa | 100% (4900/4900) | 726 ms (P50 261, P99 1058) | | 0/0 | 1/100 normal clients entered slow mode (was 19); update coverage 99.66%; fresh 87.8% |
| T3 100 clients, 10% slow 500 ms | Mac, d3142fa vs bb50641 | 98.98% vs 98.78% | 12 to 17 ms | 4.8 s vs 5.0 s | 0/0 | All 10 slow readers enter slow mode |
| T5 run 2, same profile | Ubuntu VM, e6fceec | 99.98% (4899/4900) | 802 ms | | 0/0 | **19/100 normal clients entered slow mode** (pongs 1.0 to 1.4 s, one 2.2 s); update coverage 95.50%. The two-late-pong rule is not enough |
| T5 delay_loss.sh (120±30 ms, 3% loss), 100 clients 40 s | Ubuntu VM, bb50641 | 100% (4900/4900) | 741 ms (P50 263, P99 1087) | | 0/0 | Fresh ratio 86.4%; normal update coverage 97.71%. Cause of the 2.3% missing provisionals (coalescing vs slow mode) not yet known; rerun with the new logging |

Mac and container results are only sanity checks. Report numbers must come from the Ubuntu VM (liverecall-a4) on a tagged commit.

## Open items and known limits

- **T5 on the Ubuntu VM:** one run done (finals 100%, 0 dup/stale). Still to confirm, using SLOW_MODE_ENTER and CLIENT_STATS log lines, that normal clients don't trip slow mode under delay_loss.sh, which is what the 2-late-pong rule is for. Also try bandwidth_2mbit.sh.
- **Slow-reader lag floor:** the load client buffers 16 messages, so a 500 ms reader is invisible until about 8 s behind. Short runs can't drain that backlog. This is accepted and explained in DESIGN_NOTES Gate 4. Do not send live finals as HISTORY to dodge the harness's slow-reader sleep; that would game the measurement.
- **Before/after comparison:** use experiments/baseline/ (starter, same T3/T4 parameters) as the before side.
- **Course admin:** team-size and contribution arrangement still to confirm with course staff.

## Next tasks

1. Slow-mode trigger retuned (d3142fa): T5 false trips 19 to 1. Optionally try SLOW_LATE_SECONDS = 4 for the last one; T3 on the VM still to confirm. Then try bandwidth_2mbit.sh. Reset lo afterwards. Student explanation for the new rule still to record in DESIGN_NOTES.
2. Gate 5 stress checks: bursts, repeated reconnects, longer runs, bandwidth profile.
3. Tag a pre-sleep checkpoint, then the official three-run T1 to T5 set on Ubuntu.

## Change log

- 20:45 Tue: slow-mode streak now starts when the late ping was sent and needs 3 s of lateness (2c0f320 first attempt, which broke T3; d3142fa fix). VM T5: 1/100 false trips (was 19), finals 100%, coverage 99.66%.
- 20:05 Tue: T5 run 2 with logging (e6fceec): 19/100 normal clients wrongly entered slow mode; finals 99.98%, 0 dup/stale. Trigger needs retuning. Added AI_USAGE entries for the slow-mode trigger and the rejected finals-as-HISTORY shortcut.
- 19:40 Tue: first T5 run on the VM (bb50641): finals 100%, 0 dup/stale, P95 741 ms, update coverage 97.71%. Added SLOW_MODE_ENTER and per-client CLIENT_STATS (coalesced, slow_trips, resyncs) server logs to explain the missing provisionals. The "opening handshake failed" tracebacks come from run_demo.py's TCP readiness probe and are harmless.
- 18:20 Tue: slow mode now needs 2 consecutive late pongs, so a single TCP retransmission on a lossy link can't push a normal client into finals-only mode. 19 tests OK; T3 unchanged (99.7 to 99.8%). Benefit in T5 not yet measured.
- 18:15 Tue: moved the Mac-local result files into experiments/mac-local/.
- 16:47 Tue: student explanations for Gates 3 and 4 recorded (3df34d3).
- 16:06 Tue: browser client (30106e2) and slow-client isolation (fbcb49f) committed and pushed.
