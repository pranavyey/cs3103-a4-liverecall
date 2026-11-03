**LiveRecall execution plan for 3 and 4 November 2026**

Have a complete, verified submission ready to upload by **20:00 on Wednesday, 4 November**. The deadline supplied by the student is **23:59 that day**. All times below are Singapore time.

Plan for one available student, assisted by Codex. The 14:30-to-20:00 schedule provides **23.5 hours of work blocks**, **six hours of sleep from 03:00 to 09:00**, and **3 hours 59 minutes of contingency**. Meals and short breaks fit inside the work blocks. Treat 24 hours as a ceiling, not uninterrupted focused work. Finish and upload earlier whenever possible.

The mandatory scope is a correct, usable deterministic-caption application, reproducible Ubuntu experiments, the report, the video, and submission documentation. Exclude optional ASR from this deadline plan. The assignment permits AI assistance, but the student must understand and defend the implementation.

**The execution sequence is as follows.** Each block ends with an observable result and a 10-minute explanation by the student. Reserve those 10 minutes inside each block. Trace the code path, explain the state and bounds, and describe one failure case without reading a prepared answer. Record understanding as pending until the student has actually done this. If a gate fails, use its remaining time to fix the failure before adding optional improvements.

| Singapore time | Work | Completion check |
|---|---|---|
| Tue 3 Nov, 14:30–15:30 | Finish Ubuntu setup, preserve the starter, establish Git/GitHub, run baseline checks, agree protocol invariants. | Server starts on Ubuntu; network impairment can be applied and reset; starter is recoverable; baseline logs are saved or running. |
| Tue, 15:30–18:30 | Implement server revision state, final-caption history, late join, and incremental recovery. | Older revisions cannot replace newer state; final history is ordered and excludes acknowledged finals; focused correctness checks and T1 pass. |
| Tue, 18:30–20:30 | Complete and integrate the browser client. | Two clients show revisions in place; provisional/final states differ visually; local recall defaults to 30 seconds with 15/30/60 choices; reconnect and late join work without duplicate finals. |
| Tue, 20:30–22:30 | Implement bounded sending and slow-client isolation; compare against matching evidence from the preserved starter. | Per-client pending work and retained state have explicit bounds; finals and newest active state survive overload; normal clients keep receiving revisions. If a matching baseline is missing, measure an isolated export of starter-baseline. |
| Tue 22:30–Wed 00:30 | Exercise recovery, slow readers, constrained bandwidth, bursts, and longer runs; fix integration defects. | No stale or duplicate finals; normal clients remain responsive; clients catch up promptly after impairment ends; memory/pending state remains bounded. |
| Wed, 00:30–03:00 | Choose and commit a stable candidate, then run the full T1–T5 set with three independent runs each before sleep. Assemble the accumulated design notes into a report draft and prepare the demo script. | Exact tested commit and commands recorded; full run outputs saved if stable; before/after evidence uses matching parameters; working checkpoint pushed. If unstable, record the failed gate and unfinished runs explicitly. |
| Wed, 03:00–09:00 | Sleep. | No work or approval is required from the student during this window. |
| Wed, 09:00–11:00 | Review the pre-sleep results, resolve any necessary defects, and rerun measurements required by those changes. This block is for review and corrections, not the first complete experiment attempt. | T1–T5 each have three independent runs and medians on the selected final code revision. A server/protocol/queue change triggers the full final suite on the new commit; documentation-only edits do not. Freeze feature work. |
| Wed, 11:00–14:00 | Edit and format the existing report draft into 4–5 pages; finalize required documentation. | Report draws on gate-by-gate design paragraphs and real results; architecture, protocol, recovery, overload behavior, trade-offs, limitations, and future work are covered. AI usage is an existing log, not reconstructed from memory. |
| Wed, 14:00–16:00 | Record and review the 5–7 minute demo video. | Required scenes are visible and understandable; video plays correctly and uses the exact submitted server/client. |
| Wed, 16:00–18:00 | Test the final package from a clean copy on Ubuntu; check setup instructions and all deliverables. | Required startup works within 10 seconds; final compatibility check and browser smoke test pass; report and video open; no virtual environment or unrelated files are packaged. |
| Wed, 18:00–20:00 | Rehearse the implementation explanations already practiced at each gate, finish the file audit and release checks, tag the candidate, and upload. | Student can explain the main code paths; all added/modified/untracked files have been reviewed for submission; package/repository and video are accessible; Canvas submission is confirmed. |
| Wed, 20:00–23:59 | Reserved contingency. | Correctness, packaging, upload, and access problems only. Stop discretionary edits by 22:30; aim to confirm submission by 23:00 if the early upload was blocked. |

**Codex manages implementation and verification; the student owns understanding and submission decisions.**

- Codex coordinates server, browser, and independent test/review work in parallel when their interfaces are agreed. Assign separate files to each implementation task and integrate through one coordinator.
- The student checks browser behavior, reviews design explanations, supplies team details, records or narrates the demo, handles course administration, and confirms the final submission.
- At each gate, reserve about 10 minutes for the student to explain the block's code path, invariants, memory bounds, and one failure scenario. The final walkthrough is rehearsal, not first exposure to the implementation.
- Append one short paragraph per gate to DESIGN_NOTES.md: problem, chosen design, reason, verification evidence, and remaining trade-off. Include the tested commit and open defects. By 03:00, these paragraphs and result tables should form a rough report draft.
- Update AI_USAGE.md when a useful suggestion is verified or a suggestion is rejected/modified. Record the original suggestion, the issue, the correction, and how it was checked. Do not invent an example or mark student understanding as complete without confirmation.
- Maintain FILE_AUDIT.json for every added or modified repository file, with purpose and submission disposition. Run the audit tool against starter-baseline and untracked files at each gate and again before packaging. Keep public source/test/measurement programs unchanged.
- Do not make progress depend on the unresponsive teammate. Record actual contributions and communication attempts honestly. The brief lists four-person teams while the student describes a pair; confirm the approved arrangement and contribution handling with course staff today.

**Correctness is the first release condition.**

- Accept increasing revisions per segment; never let stale state replace a final. Do not assume exactly three revisions.
- Retain enough finalized history to serve the previous 60 seconds, with explicit finite bounds on history and per-client state.
- Resume from the latest finalized state the client holds. HISTORY contains finals, oldest first, excluding acknowledged states. Test the transition from recovered history to live delivery for gaps and duplicates.
- Keep at least 60 seconds of local finalized browser history. Normal recall uses that local state.
- Under normal conditions, deliver the full revision stream. Under actual overload, replace obsolete provisional work while preserving finals and the latest active state. Return to normal delivery after catching up.
- Verify the 60-second boundary, duplicate/stale updates, variable revision counts, repeated reconnects, late joining, and recovery after overload.
- Target 100% final completeness in public tests. The brief caps hidden-performance marks at 15/30 below 99%, and 5/30 below 95%. Investigate every missing final before treating a version as complete.

**The experiment evidence must be reproducible.**

| Required test | Configuration |
|---|---|
| T1 | 20 clients, 20 seconds, three independent runs |
| T2 | 100 clients, 40 seconds, three independent runs |
| T3 | 100 clients, 60 seconds, 10% slow readers at 500 ms, three independent runs |
| T4 | 100 clients, 60 seconds, 20% disconnected at 15 seconds for 5 seconds, three independent runs |
| T5 | Ubuntu delay/jitter/loss profile, with a documented workload and three independent runs |

Use the supplied harness without changing its measurement logic. Report medians, P50/P95/P99 caption age, fresh-caption ratio, fresh-final ratio, final completeness, normal revision coverage, and recovery behavior. Separate normal and slow clients where available. Preserve raw logs, exact commands, dependency/VM versions, and the tested commit.

Use identical workload parameters for at least one before/after stress comparison. First reuse experiments/baseline/ when its exact commands, source limits, runtime, and resource conditions match the planned after run. Otherwise run the needed before measurement on an isolated export of starter-baseline, leaving the working branch untouched. A mid-implementation version is not the primary starter baseline; any separate optimization ablation must be clearly labelled.

Run the complete final suite on the chosen stable commit before sleep if possible. Record the commit with every result set; do not combine results from different code revisions into a single final table. After a server/protocol/queue fix, run the full final suite again on the replacement commit. Run impairment experiments sequentially and reset the network profile afterward. Additional bandwidth and burst checks help assess hidden-test risks, but do not replace T1–T5.

If a test's capture window ends before the source finishes, preserve the prescribed result and diagnose the timestamps. A supported option such as an explicit source-segment count may be used for a separately labelled supplemental check. Do not silently change the required run or claim that an incomplete capture proves network loss.

**The submission is complete only when all items below are checked.**

- [ ] Required Python server entry point and dependencies, plus the browser source.
- [ ] README with exact Ubuntu setup, start, test, and demo instructions.
- [ ] A 4–5 page report, excluding references and appendices, covering every required topic and the before/after comparison.
- [ ] A 5–7 minute video showing two clients, revision replacement, the default and selectable recall windows, automatic reconnect/recovery without duplicate finals, and late join.
- [ ] AI_USAGE with tools used, a verified useful suggestion, and an actual suggestion rejected or modified with an explanation.
- [ ] CONTRIBUTIONS with accurate named work and contribution percentages; do not invent a teammate's work or agreement.
- [ ] Git history and a final tagged revision that matches the code in the report/video.
- [ ] Clean-package startup and final compatibility check; the compatibility checker alone is not a correctness test.
- [ ] File audit reconciled with Git changes and untracked files; every new file has a purpose and a reviewed submission disposition; public measurement logic is unchanged.
- [ ] Canvas submission to miniProject-Assignment4-submission confirmed, including video access.
- [ ] Viva booking checked for Friday, 6 November, and all required attendees informed by the student. The live interview does not replace the video.

**Version control protects every milestone.**

The private repository is https://github.com/pranavyey/cs3103-a4-liverecall. The local remote is origin. main tracks origin/main; work/implementation tracks origin/work/implementation. main is the default branch. The original starter is tagged starter-baseline at commit 80d08b8.

Commit coherent changes on work/implementation and push after each verified milestone. Advance main only after integration checks pass. Create descriptive tags for the correct server, working demo, pre-sleep checkpoint, submission candidate, and actual submitted revision. Add tags only after their checks have passed.

For recovery, preserve current work and create a new branch from the last good tag, or revert an identified bad commit. Avoid destructive resets and force pushes. A separately verified local bundle also preserves the original starter if the working folder becomes unusable.

**Reduce scope before consuming the contingency.**

If Ubuntu is still unusable by 16:00 today, treat environment access as the immediate blocker while independent implementation continues. If correctness is still failing at 23:00, stop cosmetic work and extra tuning. After 11:00 tomorrow, allow only necessary correctness or reproducibility fixes and rerun affected checks. Protect report, video, and upload time. Optional ASR stays out of scope.

Requirements are based on the supplied miniProject_Assignment4_LiveRecall_System.pdf, especially Sections 3–6 and 8–15, and the supplied public-test/demo/setup guides. The deadline time and sleep window were supplied by the student. Scheduling allocations and checkpoints are the execution plan, not guarantees about hidden evaluation performance.
