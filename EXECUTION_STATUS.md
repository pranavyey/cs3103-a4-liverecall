# LiveRecall execution status

Live tracker that sits next to EXECUTION_PLAN.md. Any agent or session picking up the work reads this first and updates it at each gate: what passed, the commit, open defects, and the next task. Times are Singapore time.

**Last updated:** Tue 3 Nov 2026, 23:33, by Claude (chat session with Pranav)
**Branch:** work/implementation, tracking origin/work/implementation. main is not advanced yet.
**Current plan block:** Tue 22:30 to Wed 00:30 (Gate 5: stress, recovery, bandwidth, long runs). Gate 4 finished about 23:15, roughly 45 min past its block; Gate 5 is partly done.

## Gates

| Gate | Plan block | State | Commit | Evidence |
|---|---|---|---|---|
| 1. Environment and baseline | Tue 14:30 to 15:30 | Done | cc8e6b7, 8d77709 | experiments/baseline/ (starter T1, T3, T4 on Ubuntu VM) |
| 2. Server revisions, history, late join, recovery | Tue 15:30 to 18:30 | Done | 36ed410 (tag server-core-tested) | experiments/server-core/, tests/test_server_core.py |
| 3. Browser client | Tue 18:30 to 20:30 | Done | 30106e2 | tests/browser_e2e.js (2 tabs + late joiner, no gaps or duplicates) |
| 4. Bounded sending, slow-client isolation | Tue 20:30 to 22:30 | Design done; T5 check outstanding | fbcb49f, plus the late-pong change (see log) | One-run dev checks only (see below) |
| 5. Stress, recovery, bandwidth, long runs | Tue 22:30 to Wed 00:30 | Done | b1961d3 (tools/stress_reconnect.py), server 79c9720 | VM gate5/ folder: reconnect, storm, 10-min memory, impairment recovery |
| 6. Required T1 to T5 on Ubuntu, 3 runs each | Wed 00:30 to 03:00, 09:00 to 11:00 | Done (candidate-1) | e77a2b9, tag candidate-1 | experiments/official/candidate-1/ |
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
| T3 prescribed (100 clients, 60 s, 10% slow 500 ms) | Ubuntu VM, 405da57 vs bb50641 | 88.42% vs 89.82% | 20 ms both | 6.4 s vs 6.3 s | 0/0 | **Capture cutoff**: results written before SOURCE_DONE in both. All 10 slow readers caught at late_for=6.0 s |
| T5 delay_loss.sh, 100 clients 40 s | Ubuntu VM, 405da57 | 99.98% | 752 ms | | 0/0 | 1 slow-mode entry, a genuine 4.0 s pong (late_for=4.0 s); coverage 99.41% |
| T5 bandwidth_2mbit.sh, 100 clients 40 s | Ubuntu VM, 405da57 | 89.80% (44/49 for every client) | 50 ms | | 0/0 | Capture cutoff. With --source-segments 40 (SOURCE_DONE first): **100%**, coverage 100%, 0 slow-mode entries |
| T5 run 3, same profile | Ubuntu VM, d3142fa | 100% (4900/4900) | 726 ms (P50 261, P99 1058) | | 0/0 | 1/100 normal clients entered slow mode (was 19); update coverage 99.66%; fresh 87.8% |
| T3 100 clients, 10% slow 500 ms | Mac, d3142fa vs bb50641 | 98.98% vs 98.78% | 12 to 17 ms | 4.8 s vs 5.0 s | 0/0 | All 10 slow readers enter slow mode |
| T5 run 2, same profile | Ubuntu VM, e6fceec | 99.98% (4899/4900) | 802 ms | | 0/0 | **19/100 normal clients entered slow mode** (pongs 1.0 to 1.4 s, one 2.2 s); update coverage 95.50%. The two-late-pong rule is not enough |
| T5 delay_loss.sh (120±30 ms, 3% loss), 100 clients 40 s | Ubuntu VM, bb50641 | 100% (4900/4900) | 741 ms (P50 263, P99 1087) | | 0/0 | Fresh ratio 86.4%; normal update coverage 97.71%. Cause of the 2.3% missing provisionals (coalescing vs slow mode) not yet known; rerun with the new logging |

Mac and container results are only sanity checks. Report numbers must come from the Ubuntu VM (liverecall-a4) on a tagged commit.

## Open items and known limits

- **Course clarification (bounded history, graceful overload):** checked against the server. Client history requests are now capped at 60 s instead of rejected over 60, and finals are retained for 70 s (79c9720). Per-client pending state stays bounded (256 items / 2 MiB); finals are never dropped for provisionals. VM check for 79c9720: 21 tests OK; T4 with --source-segments 40 gave 100%, 120 recovered items, 0 dup/stale.
- **VM capture cutoff (environment limit, not the server):** on the VM the source takes about 70 s for 76 segments (0.92 s each, not the 0.75 s run_demo.py budgets), with **1 client and an idle VM** as well as with 100 clients. Results are written at 60.4 s, so the last 12 segments are never captured (1 client: 84.21%). Server load is not the cause. A 0.2 s asyncio.sleep measured 0.217 to 0.275 s on the VM (5 tries, about 50 ms over on average, though each try includes event-loop start-up); three waits per segment at that overshoot give about 0.9 s per segment, matching the observed 0.92 s. Measured inside one event loop (20 waits): 0.2517 s per 0.2 s wait, so 51.7 ms over and 0.905 s per segment. Report it with this evidence; use --source-segments supplemental runs for completeness claims, as the baseline did; do not change the harness. Ask course staff whether grading uses a machine where the source keeps 0.75 s pacing.
- **T5 on the Ubuntu VM:** one run done (finals 100%, 0 dup/stale). Still to confirm, using SLOW_MODE_ENTER and CLIENT_STATS log lines, that normal clients don't trip slow mode under delay_loss.sh, which is what the 2-late-pong rule is for. Also try bandwidth_2mbit.sh.
- **Slow-reader lag floor:** the load client buffers 16 messages, so a 500 ms reader is invisible until about 8 s behind. Short runs can't drain that backlog. This is accepted and explained in DESIGN_NOTES Gate 4. Do not send live finals as HISTORY to dodge the harness's slow-reader sleep; that would game the measurement.
- **Before/after comparison:** use experiments/baseline/ (starter, same T3/T4 parameters) as the before side.
- **Course admin:** team-size and contribution arrangement still to confirm with course staff.

## Next tasks

1. Slow-mode rule final for now (405da57); VM T3/T5 checked. Record the student's Gate 4 explanation in DESIGN_NOTES and finish the AI_USAGE entries.
2. Capture cutoff explained (VM timer overshoot, see open items). Plan the official runs to state it and add --source-segments supplemental runs.
3. Gate 5 stress checks: bursts, repeated reconnects, longer runs, bandwidth profile.
4. Tag a pre-sleep checkpoint, then the official three-run T1 to T5 set on Ubuntu.

## Change log

- 02:03 Wed: official set on candidate-1 finished: 33 runs, all exit 0, 0 dup/stale. Prescribed T1 to T4 all cut off on the VM (95.45 / 87.76 / 91.18 / 85.53%); T5 100% with 0 slow-mode entries; every supplemental run 100%. The summary script's cut-off count was wrong (said 1 of 3) and was fixed; SUMMARY.txt recomputed. Results copied to experiments/official/candidate-1/ and report_dump.md.
- 01:35 Wed: first official attempt spoiled: the pasted commands ran the script twice (inside and outside tmux), sharing port 8765 and the output folder. Killed and restarted cleanly at 01:37.
- Gate 5 item 3 (VM, b1961d3): delay_loss.sh applied from 29 s to 69 s of a 120 s run. Normal-client P95 by 10 s window: about 21 ms before; 476 to 1011 ms during (fresh 82.8 to 95.9%); 20.9 ms and 100% fresh in the first window after reset. 0 slow-mode entries, 100% completeness, 0 dup/stale. **Gate 5 done.**
- Gate 5 item 2 (VM, b1961d3): 10-minute run, 100 clients, 10% slow, 600 segments. RSS 32.3 MB at 1 min, 32.4 MB at the end (flat). Completeness 100%, 0 dup/stale, normal P95 19.9 ms and 100% fresh (all 162000 normal revisions received), slow P50 1.4 s / P95 9.0 s, 60 slow-mode entries, no resyncs.
- Gate 5 item 1 (VM, b1961d3, tools/stress_reconnect.py): 100 clients x 60 segments. Random reconnects: 1111 connects, 2023 finals recovered, HISTORY P95 2.9 ms. Storm (all reconnect together every 4 s): 1500 connects, 900 recovered, HISTORY P95 16.1 ms. Both 100/100 clients complete, 0 duplicate, 0 stale, no coalescing or resyncs.
- 23:30 Tue: VM T4 on 79c9720 passed (100%, 0 dup/stale). Added report_dump.md, raw material for the report.
- 23:25 Tue: 79c9720 caps history requests at 60 s (were rejected over 60) and retains 70 s internally. 21 tests OK; local T4 100%, 0 dup/stale.
- 23:10 Tue: cutoff measured on the VM: the source takes about 70 s for 76 segments even with 1 client on an idle VM, so it is the VM's pacing, not server load.
- 21:30 Tue: 405da57 measures the late streak only up to the latest late pong (fixes fast pongs extending it). VM: T3 slow readers all caught; T5 one genuine 4 s trip; 2 Mbit 100% once the run isn't cut off. Found the VM capture cutoff behind the 88 to 91% T3 numbers.
- 20:45 Tue: slow-mode streak now starts when the late ping was sent and needs 3 s of lateness (2c0f320 first attempt, which broke T3; d3142fa fix). VM T5: 1/100 false trips (was 19), finals 100%, coverage 99.66%.
- 20:05 Tue: T5 run 2 with logging (e6fceec): 19/100 normal clients wrongly entered slow mode; finals 99.98%, 0 dup/stale. Trigger needs retuning. Added AI_USAGE entries for the slow-mode trigger and the rejected finals-as-HISTORY shortcut.
- 19:40 Tue: first T5 run on the VM (bb50641): finals 100%, 0 dup/stale, P95 741 ms, update coverage 97.71%. Added SLOW_MODE_ENTER and per-client CLIENT_STATS (coalesced, slow_trips, resyncs) server logs to explain the missing provisionals. The "opening handshake failed" tracebacks come from run_demo.py's TCP readiness probe and are harmless.
- 18:20 Tue: slow mode now needs 2 consecutive late pongs, so a single TCP retransmission on a lossy link can't push a normal client into finals-only mode. 19 tests OK; T3 unchanged (99.7 to 99.8%). Benefit in T5 not yet measured.
- 18:15 Tue: moved the Mac-local result files into experiments/mac-local/.
- 16:47 Tue: student explanations for Gates 3 and 4 recorded (3df34d3).
- 16:06 Tue: browser client (30106e2) and slow-client isolation (fbcb49f) committed and pushed.
