#!/usr/bin/env bash
# Gate 6: official public test set on the Ubuntu VM.
#
#   ./tools/run_official.sh <commit-or-tag>
#
# Runs T1 to T5 with the spec's commands (3 runs each, unmodified harness),
# then supplemental runs with --source-segments so the source finishes before
# capture ends (the VM's source pacing is about 0.905 s per segment, not the
# 0.75 s run_demo.py budgets). Everything goes into official/<label>/.
# Loopback is always reset on exit, even if a run fails or is interrupted.
set -uo pipefail

LABEL="${1:?usage: $0 <commit-or-tag>}"
cd "$(dirname "$0")/.."
OUT="official/$LABEL"
mkdir -p "$OUT"
trap 'sudo ./network_profiles/reset.sh lo >/dev/null 2>&1; echo "lo reset: $(tc qdisc show dev lo)"' EXIT

# The source sends over lo too; start every run on a clean link.
sudo ./network_profiles/reset.sh lo >/dev/null 2>&1 || true
chmod +x network_profiles/*.sh

{
  echo "label: $LABEL"
  echo "date: $(date -Is)"
  echo "host: $(hostname)  cpus: $(nproc)"
  uname -a
  grep PRETTY_NAME /etc/os-release
  python --version
  pip freeze 2>/dev/null || uv pip freeze 2>/dev/null || python -m pip freeze
  echo "qdisc before runs: $(tc qdisc show dev lo)"
} > "$OUT/environment.txt" 2>&1

python -m unittest discover tests > "$OUT/unit_tests.txt" 2>&1
tail -1 "$OUT/unit_tests.txt"

run () {   # run <name> <run_demo args...>   (server output kept for SLOW_MODE_ENTER)
  local name="$1"; shift
  echo "=== $name  ($(date +%H:%M:%S))  run_demo.py $*" | tee -a "$OUT/commands.txt"
  python run_demo.py "$@" --output-stem "$OUT/$name" > "$OUT/$name.log" 2>&1
  echo "    exit $?"
}

# --- Required public tests (spec section 8 commands, 3 runs each) ---
run t1 --clients 20  --duration 20 --runs 3
run t2 --clients 100 --duration 40 --runs 3
run t3 --clients 100 --duration 60 --runs 3 --slow-percent 10 --slow-ms 500
run t4 --clients 100 --duration 60 --runs 3 --disconnect-percent 20 --disconnect-at 15 --disconnect-seconds 5
sudo ./network_profiles/delay_loss.sh lo > /dev/null
echo "T5 qdisc: $(tc qdisc show dev lo)" >> "$OUT/commands.txt"
run t5 --clients 100 --duration 40 --runs 3
sudo ./network_profiles/reset.sh lo > /dev/null

# --- Supplemental: same tests, fewer segments so no capture cutoff ---
run t1_supp --clients 20  --duration 20 --runs 3 --source-segments 17
run t2_supp --clients 100 --duration 40 --runs 3 --source-segments 38
run t3_supp --clients 100 --duration 60 --runs 3 --slow-percent 10 --slow-ms 500 --source-segments 60
run t4_supp --clients 100 --duration 60 --runs 3 --disconnect-percent 20 --disconnect-at 15 --disconnect-seconds 5 --source-segments 60
sudo ./network_profiles/delay_loss.sh lo > /dev/null
run t5_supp --clients 100 --duration 40 --runs 3 --source-segments 35
sudo ./network_profiles/reset.sh lo > /dev/null
sudo ./network_profiles/bandwidth_2mbit.sh lo > /dev/null
run t5_bw_supp --clients 100 --duration 40 --runs 3 --source-segments 38
sudo ./network_profiles/reset.sh lo > /dev/null

# --- Summary ---
{
  for f in t1 t2 t3 t4 t5 t1_supp t2_supp t3_supp t4_supp t5_supp t5_bw_supp; do
    log="$OUT/$f.log"
    echo "================ $f"
    # Each run prints SOURCE_DONE and "Results written" once, in some order;
    # a run is cut off if "Results written" comes first in its pair.
    grep -o -E 'SOURCE_DONE|Results written' "$log" |
      awk '{k++; if(k%2==1){n++; if($0=="Results written")c++}}
           END{printf "runs: %d, cut off (results before SOURCE_DONE): %d\n", n, c}'
    echo "SLOW_MODE_ENTER lines: $(grep -c SLOW_MODE_ENTER "$log")  clients: $(grep SLOW_MODE_ENTER "$log" | grep -o 'client=[^ ]*' | sort -u | wc -l)"
    echo "duplicates by run: $(grep 'Duplicate messages' "$log" | awk '{printf "%s ", $NF}')  stale by run: $(grep 'Stale messages' "$log" | awk '{printf "%s ", $NF}')"
    sed -n '/=== Median across independent runs ===/,/^$/p' "$log"
  done
} > "$OUT/SUMMARY.txt"
cat "$OUT/SUMMARY.txt"
echo "Saved in $OUT  ($(date +%H:%M:%S))"
