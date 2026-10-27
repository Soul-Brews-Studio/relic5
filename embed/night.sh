#!/bin/zsh
# embed/night.sh: one night of LLM work on gb300, in order, done by a set time (Nat, 2026-10-26: "i need job ~12h to
# finish 6am"). Each step resumes where an earlier run stopped (ledgers in ~/.cache/relic5), so it can be started again.
#   1. Discord: wait for embed/discord-all.sh to finish, then run it once more, for servers verified after it started
#   2. relic5 bank, the LLM precision pass in value order: thinking, then git (embed/hindsight-import.py --upgrade)
# Nothing new is sent after UNTIL (default 05:30): what is queued then finishes on its own, so gb300 is free at 06:00.
#   embed/night.sh [HH:MM]
set -u
HERE=${0:A:h}
UNTIL=${1:-05:30}
LOG=~/Library/Logs/hindsight-import.log
past() { python3 -c "import sys,time; h,m=map(int,sys.argv[1].split(':')); t=time.localtime(); sys.exit(0 if (t.tm_hour,t.tm_min)>=(h,m) and t.tm_hour-h<12 else 1)" "$UNTIL"; }
say() { echo "$(date '+%F %T') night: $*" | tee -a "$LOG"; }

say "start; nothing new after $UNTIL"
while pgrep -f "embed/discord-all.sh" >/dev/null; do
  past && { say "past $UNTIL while Discord still runs; stopping here"; exit 0; }
  sleep 60
done
past || { say "Discord: one more pass for servers verified later"; zsh "$HERE/discord-all.sh" 2>&1 | tee -a "$LOG" | grep -E "^==|queued|failed|Error" ; }
# the Discord banks' queue first: the relic5 pass starts when they are nearly drained
until past; do
  open=$(curl -s -m 20 127.0.0.1:8888/v1/default/banks | python3 -c "
import json,sys,urllib.request
n=0
for b in json.load(sys.stdin).get('banks',[]):
    if b['bank_id'].startswith('discord-'):
        s=json.load(urllib.request.urlopen(f\"http://127.0.0.1:8888/v1/default/banks/{b['bank_id']}/stats\",timeout=20))
        n+=s.get('pending_operations',0)
print(n)" 2>/dev/null || echo 999)
  [ "${open:-999}" -le 10 ] && break
  sleep 60
done
for src in thinking git; do
  past && { say "past $UNTIL; $src not started"; break; }
  say "relic5 upgrade: $src"
  python3 "$HERE/hindsight-import.py" "$src" --upgrade --until "$UNTIL" --max-pending 120 2>&1 | tee -a "$LOG" | grep -Ev "^\s*$"
done
say "done"
