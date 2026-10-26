#!/bin/zsh
# embed/start.sh: bring up, by hand, what Hindsight on m5 needs (Nat, 2026-10-26: no autostart on m5; started when wanted).
#   1. gb300: embed/gb300-serve.py (embeddinggemma-300m bf16 + the bge-reranker-v2-m3 cross-encoder), 127.0.0.1:11437 there,
#      in a herdr pane on gb300 (herdr --machine gb300)
#   2. m5: one ssh tunnel to gb300 (11437 the embed server, 11510 the qwen3.8-27b vLLM Hindsight uses as its LLM)
#   3. m5: embed/embed-router.py on 127.0.0.1:11436 (big batches gb300 first, small ones the ANE first), in tmux
#   4. m5: the hindsight-embed daemon (profile "relic"; it stops itself after a while idle)
# Every step is skipped when it is already up. Check afterwards: relic5 memory status
set -u
HERE=${0:A:h}
GB=${GB300:-gb300}
up() { curl -s -m 3 "$1" >/dev/null 2>&1; }

if ssh -o BatchMode=yes $GB 'curl -s -m 3 127.0.0.1:11437/health' </dev/null 2>/dev/null | grep -q '"status": "ok"'; then
  echo "gb300 embed server: up"
else
  scp -q "$HERE/gb300-serve.py" $GB:embed-serve/gb300-serve.py
  # in a herdr pane on gb300 (a saved herdr machine): it outlives any ssh session (gb300 drops them) and can be read
  # from here with: herdr --machine gb300 pane read w1:p1 --source recent-unwrapped --lines 20
  PANE=$(herdr --machine gb300 pane list 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin)['result']['panes'][0]['pane_id'])" 2>/dev/null)
  herdr --machine gb300 pane run "${PANE:-w1:p1}" 'cd ~/embed-serve && HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false ~/.local/bin/uv run gb300-serve.py --rerank BAAI/bge-reranker-v2-m3' >/dev/null
  echo "gb300 embed server: starting in herdr pane ${PANE:-w1:p1} on gb300"
fi

if up 127.0.0.1:11437/health && up 127.0.0.1:11510/v1/models; then
  echo "tunnel: up"
else
  ssh -f -N -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
    -L 127.0.0.1:11437:127.0.0.1:11437 -L 127.0.0.1:11510:127.0.0.1:11510 $GB && echo "tunnel: started"
fi

# m5's own LLM worker for the router's /v1/chat/completions split (Ollama qwen3.6 on the M5 Max GPU)
if up 127.0.0.1:11434/api/tags; then
  echo "ollama (m5 LLM worker): up"
else
  tmux new-session -d -s ollama "ollama serve" && echo "ollama: started (tmux attach -t ollama)"
fi

if up 127.0.0.1:11436/health; then
  echo "embed router: up"
else
  tmux new-session -d -s embed-router "python3 $HERE/embed-router.py" && echo "embed router: started (tmux attach -t embed-router)"
fi

for i in $(seq 1 60); do up 127.0.0.1:11437/health && break; sleep 2; done
if ! up 127.0.0.1:8888/health; then
  hindsight-embed -p relic daemon start >/dev/null 2>&1
  for i in $(seq 1 60); do up 127.0.0.1:8888/health && break; sleep 2; done   # the first start loads its models
fi
up 127.0.0.1:8888/health && echo "hindsight: up (http://127.0.0.1:8888)" || echo "hindsight: not up (hindsight-embed daemon logs)"
relic5 memory status 2>/dev/null || true
