# LiveRecall

A WebSocket caption server and browser client. They show live, revision-based captions and let a student recall the last 15, 30 or 60 seconds after a short distraction or a dropped connection.

## Team members

- Pranav Mahatma / A0281778L: all components (server, browser client, experiments, report). See CONTRIBUTIONS.md.

## Ubuntu setup

Official results: Ubuntu 26.04.1 LTS in a UTM VM (Apple Virtualization, ARM64, 2 CPUs, 4 GB RAM) with Python 3.12.16. Also tested on Ubuntu 24.04.5 LTS (Multipass) with Python 3.12.3. From a fresh Ubuntu machine:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip iproute2
```

On macOS, I used **UTM** (mac.getutm.app) with **Virtualize → Linux → Use Apple Virtualization**, the Ubuntu Server ARM64 ISO, 2 CPUs, 4 GB RAM and a 20 GB disk, with OpenSSH enabled during install. Copy the code in with `scp` and work over `ssh`.

If you reproduce the public tests on a VM, check its timer accuracy first: the public harness assumes the source spends 0.75 s per segment. On my Multipass VM the sleeps ran about 25% long, which cut off the prescribed runs (report.pdf, Section 4.2). The server itself does not depend on timer accuracy.

```bash
python3 -c "import asyncio,time;exec('async def m():\n t=time.perf_counter()\n for _ in range(20): await asyncio.sleep(0.2)\n print((time.perf_counter()-t)/20)');asyncio.run(m())"
# expect about 0.200-0.205 (Multipass gave 0.252; UTM gave 0.202)
```

## Install

From the repository root:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

If the system Python is not 3.12 (Ubuntu 26.04 ships 3.14), I used `uv` to get 3.12: `curl -LsSf https://astral.sh/uv/install.sh | sh`, then `uv venv -p 3.12 venv && source venv/bin/activate && uv pip install -r requirements.txt`.

The only dependency is `websockets` (>=13, <17; tested with 16.1.1). The server needs no internet access, cloud API or database.

## Required server

```bash
python solution_server.py --port 8765
```

The server listens on `0.0.0.0:<port>`. It is ready in well under a second and takes no interactive input. To check that it starts and the required files are present:

```bash
python submission_check.py
```

The unit and integration tests (22 tests):

```bash
python -m unittest discover tests
```

## Browser client

The client is plain HTML and JavaScript in `client/`, with no build step. You need three terminals, all in the repository root with the venv active:

```bash
# Terminal 1: server
python solution_server.py --port 8765

# Terminal 2: serve the browser files
python3 -m http.server 8000 --bind 0.0.0.0 --directory client

# Terminal 3: caption source (start it after the browser tabs are open)
python caption_source.py --duration 120
```

Open `http://127.0.0.1:8000` in a browser. The page connects to `ws://<host the page came from>:8765`, session `L1`. If the server runs on a VM, open `http://<vm-ip>:8000` from the host instead (find the IP with `hostname -I` inside the VM). To choose the server or session explicitly, use `http://<host>:8000/?server=ws://<host>:8765&session=L1`.

## Public deterministic tests

These use the unmodified harness and the spec's commands, 3 independent runs each; I report the median. Run them inside the Ubuntu VM so `tc/netem` can be applied to `lo`:

```bash
chmod +x network_profiles/*.sh
sudo ./network_profiles/reset.sh lo

python run_demo.py --clients 20  --duration 20 --runs 3                                    # T1
python run_demo.py --clients 100 --duration 40 --runs 3                                    # T2
python run_demo.py --clients 100 --duration 60 --runs 3 --slow-percent 10 --slow-ms 500    # T3
python run_demo.py --clients 100 --duration 60 --runs 3 --disconnect-percent 20 --disconnect-at 15 --disconnect-seconds 5   # T4

sudo ./network_profiles/delay_loss.sh lo                                                   # T5
python run_demo.py --clients 100 --duration 40 --runs 3 --output-stem t5
sudo ./network_profiles/reset.sh lo
```

`tools/run_official.sh <label>` runs all of the above in one go (about 25 minutes). It also runs supplemental versions with `--source-segments` (17/38/60/60/35), which finish early even on a VM with slow timers, and an extra T5 at 2 Mbit. It writes logs, CSV/JSON and `SUMMARY.txt` (medians, cut-off check, slow-mode entries, duplicates and stale per run) into `official/<label>/`, and always resets `lo` on exit. Run `sudo -v` first: the script calls `sudo tc`.

```bash
sudo -v
tmux new -d -s official "./tools/run_official.sh <label>"
```

Results: `experiments/official/candidate-2/` (final code on UTM, used in the report), `experiments/official/candidate-1-utm/` (previous tag on UTM) and `experiments/official/candidate-1/` (Multipass, cut off by slow timers).

Extra stress tools (these don't change any public file):

```bash
python tools/stress_reconnect.py --clients 100 --segments 60           # repeated random reconnects
python tools/stress_reconnect.py --clients 100 --segments 60 --storm   # all clients reconnect together every 4 s
```

## Mandatory deterministic application demo

1. Start the server, the static file server and the browser as in "Browser client" above. Open **two** tabs.
2. Start `python caption_source.py --duration 120`.
3. **Revision replacement:** provisional lines (amber, italic, with a revision number) are replaced in place by newer revisions and then by the final (black, "final" tag). A segment never appears twice.
4. **"What did I miss?":** the panel shows the last 30 s by default. Switch to 15 s and 60 s.
5. **Disconnect and recovery:** press **Simulate disconnect** in one tab. Wait a few seconds; the countdown shows the reconnect. The tab then resumes from the last final it holds: the missed finals arrive through HISTORY, with no gaps and no duplicates.
6. **Late join:** open a third tab partway through. It gets the last 60 s of finals and the current provisional state straight away.

## Design notes

Full per-gate notes are in DESIGN_NOTES.md; report.pdf has the measurements.

- **Revision and deduplication state:** the server keeps the latest revision of each active segment, plus a high-water mark of the highest segment seen. It accepts only higher revisions. Duplicates, older revisions and anything after a final are dropped, and a final never changes.
- **Bounded server history:** finals are kept for 70 s, and at most 32,768 items or 32 MiB. A client may request up to 60 s; longer requests are capped to 60 s, not rejected. Active (not yet final) segments are capped at 128 items and 4 MiB; over the cap, the oldest open segment is evicted and the source stays connected, so abandoned segments never block later finals.
- **Reconnect and late-join recovery:** a client sends its last final as `(last_segment, last_revision)`. The server replies with HISTORY containing only newer finals, then the current active segments, then live updates. The snapshot and the client's registration happen with no `await` in between, so no final can fall between them (no gap) or be sent twice (no duplicate). Large HISTORY is split into frames under the client's 1 MiB limit.
- **Per-client buffering and backpressure:** each client has its own bounded queue and sender task, so a slow client never blocks the source or other clients. The server sends a WebSocket ping every 2 messages and allows at most 2 unanswered. This keeps the backlog in the server's queue instead of hidden TCP and library buffers, and once a client falls behind, superseded provisionals are dropped from its queue (coalesced). Finals and the newest revision of each segment are always kept.
- **Overload behaviour and trade-offs:**
  - Slow mode: if a client's late pongs (over 1 s) show it has not read for at least 3 s, it gets finals only for 15 s. The hold doubles on each repeat, up to 120 s. After the hold it returns to full updates.
  - Hard limit: if a queue still exceeds 256 items or 2 MiB, it is cleared and the client is resynchronised from history, not disconnected.
  - Trade-off: slow readers see fewer provisional revisions, while normal clients stay fresh and finals stay complete.

## Optional ASR bonus

Not attempted.
