#!/bin/bash
# relic5's LLM work on gb300 at night only (Nat, 2026-10-27: "stop and just start after midnight", then "start again at
# 22:00 to 10:00"). Every night: at 22:00 the router gets its full gb300 share (34) and relic5's consolidation is
# switched on; the readings (no LLM), then the sessions and vault full extraction run, sending nothing new after
# 09:30; at 10:00 consolidation is switched off, open relic5 jobs are cancelled and the router drops to 4 (enough for
# a question by hand). Each step resumes from its ledger. Log: ~/logs/relic5-night.log
cd ~/relic5/app || exit 1
START=${START:-22:00}; LAST=${LAST:-09:30}; END=${END:-10:00}; NIGHT=${NIGHT_SLOTS:-34}; DAY=${DAY_SLOTS:-4}
LOG=~/logs/relic5-night.log
say() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }
slots() {
  curl -s -m 10 -X POST 127.0.0.1:11436/workers -H 'Content-Type: application/json' -d "{\"kind\":\"llm\",\"name\":\"gb300\",\"url\":\"http://127.0.0.1:11510/v1/chat/completions\",\"model\":\"qwen3.8-27b\",\"slots\":$1,\"extra\":{\"chat_template_kwargs\":{\"enable_thinking\":false}},\"note\":\"relic5-night.sh: $2\"}" >/dev/null && say "router llm slots $1 ($2)"
}
consolidation() {
  curl -s -m 30 -X PATCH 127.0.0.1:8888/v1/default/banks/relic5/config -H 'Content-Type: application/json' -d "{\"updates\":{\"enable_auto_consolidation\":$1}}" >/dev/null && say "relic5 auto consolidation $1"
}
until_time() {   # sleep until HH:MM (today, or tomorrow if it has passed)
  local now t; now=$(date +%s); t=$(date -d "$1" +%s); [ "$t" -le "$now" ] && t=$(date -d "tomorrow $1" +%s)
  say "waiting until $(date -d @"$t" '+%F %H:%M')"; sleep $(( t - now ))
}
in_night() { local h; h=$(date +%H%M); [ "$h" -ge "${START/:/}" ] || [ "$h" -lt "${LAST/:/}" ]; }
say "night runner start (window $START-$END, nothing new after $LAST)"
# the first night starts at $START even when the runner is started inside the window (09:14 on 2026-10-27 it began at
# once); RUN_NOW=1 starts the first night right away
[ "${RUN_NOW:-0}" = 1 ] || until_time "$START"
while true; do
  in_night || until_time "$START"
  slots "$NIGHT" "night"; consolidation true
  python3 embed/hindsight-import.py readings --strategy embed-first 2>&1 | tee -a ~/logs/hindsight-import.log | grep -E "items on the hub|all .* queued|failed|Error|RELIC5" | tee -a "$LOG"
  for s in sessions vault; do
    in_night || break
    say "full extraction: $s"
    python3 embed/hindsight-import.py "$s" --upgrade --until "$LAST" --max-pending 120 2>&1 | tee -a ~/logs/hindsight-import.log | grep -Ev "^\s*$" | tail -3 | tee -a "$LOG"
  done
  until_time "$END"
  consolidation false; python3 embed/hindsight-cancel-ops.py relic5 | tee -a "$LOG"; slots "$DAY" "day"
done
