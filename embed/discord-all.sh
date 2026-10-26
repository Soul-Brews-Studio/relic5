#!/bin/zsh
# embed/discord-all.sh: every Discord server backup (maw atlas, on m5) into its own Hindsight bank, smallest first,
# full LLM extraction, observations on (Nat, 2026-10-26: "separate 1 per [server] to dig about the insight each server").
# Each server is queued by embed/hindsight-import.py (resumable: a re-run skips what is queued or already there); the
# hindsight daemon then extracts in queue order on the dispatcher's LLM workers. Watch: relic5 hindsight status --bank B
#   embed/discord-all.sh            # all finished servers
set -u
HERE=${0:A:h}
LOG=~/Library/Logs/hindsight-import.log
python3 "$HERE/discord-source.py" --list | python3 -c "
import json,sys
rows=[json.loads(l) for l in sys.stdin]
for r in sorted(rows, key=lambda r: r['messages']):
    print(r['guild'], r['bank'], r['messages'])" | while read -r gid bank n; do
  echo "== $bank ($n messages)"
  python3 "$HERE/hindsight-import.py" "discord:$gid" 2>&1 | tee -a "$LOG" | grep -E "created|items on the hub|all .* queued|failed|Error" || true
done
echo "all servers queued; per bank: relic5 hindsight status --bank <bank> (banks: ~/.config/relic5/discord-banks.json)"
