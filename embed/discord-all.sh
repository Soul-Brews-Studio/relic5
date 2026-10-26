#!/bin/zsh
# embed/discord-all.sh: every Discord server backup (maw atlas, on m5) into its own Hindsight bank, smallest first,
# full LLM extraction, observations on (Nat, 2026-10-26: "separate 1 per [server] to dig about the insight each server").
# Each server is queued by embed/hindsight-import.py (resumable: a re-run skips what is queued or already there); the
# hindsight daemon then extracts in queue order on the dispatcher's LLM workers. Watch: relic5 hindsight status --bank B
#   embed/discord-all.sh            # all finished servers
set -u
HERE=${0:A:h}
LOG=~/Library/Logs/hindsight-import.log
# the job's size up front, for the overall progress bar of `relic5 hindsight speed` and `top`: items per bank
python3 - "$HERE" <<'PY'
import json, os, subprocess, sys, time
here = sys.argv[1]
rows = [json.loads(l) for l in subprocess.run([sys.executable, f"{here}/discord-source.py", "--list"], capture_output=True, text=True).stdout.splitlines()]
banks = {}
for r in rows:
    n = subprocess.run([sys.executable, f"{here}/discord-source.py", r["guild"]], capture_output=True, text=True).stdout.count("\n")
    banks[r["bank"]] = banks.get(r["bank"], 0) + n
out = os.path.expanduser("~/.cache/relic5/hindsight-job.json")
json.dump({"name": "discord → per-server banks", "banks": banks, "started": time.time()}, open(out + ".tmp", "w"))
os.replace(out + ".tmp", out)
print(f"job: {sum(banks.values()):,} items in {len(banks)} banks ({out})")
PY
python3 "$HERE/discord-source.py" --list | python3 -c "
import json,sys
rows=[json.loads(l) for l in sys.stdin]
for r in sorted(rows, key=lambda r: r['messages']):
    print(r['guild'], r['bank'], r['messages'])" | while read -r gid bank n; do
  echo "== $bank ($n messages)"
  python3 "$HERE/hindsight-import.py" "discord:$gid" 2>&1 | tee -a "$LOG" | grep -E "created|items on the hub|all .* queued|failed|Error" || true
done
echo "all servers queued; per bank: relic5 hindsight status --bank <bank> (banks: ~/.config/relic5/discord-banks.json)"
