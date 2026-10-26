# HINDSIGHT: relic5's history as memory, embedded on gb300 and the ANE

Nat, 2026-10-26: "install hindsight and use gb300 to embed? make it compat work with ane on m5 too?", "if huge can we
go gb300 first?", "can we add more to make our cli compat with hindsight?". relic5 keeps every turn; Hindsight
(vectorize-io/hindsight, the `hindsight-embed` daemon on m5) keeps what was learned from them: facts, entities,
observations, mental models.

**Names (Nat, 2026-10-26):** `relic5 hindsight …` is this bank. `relic5 memory …` is relic5's own memory, the Claude Code
memory notes on the hub (`status`, `list`, `search`); its old Hindsight subcommands (`recall`, `retain`, `import`,
`workers`, `top`) still work and forward to `relic5 hindsight` with a note.

## The pieces

```
relic5 hindsight …  ──►  hindsight-embed daemon (m5, 127.0.0.1:8888, profile "relic", its own pg0 database)
                        │ LLM, embeddings, rerank ▼
                      embed/embed-router.py (m5, 127.0.0.1:11436)
                        ├─ ≥ 32 texts: split by speed, both at once ─► embed/gb300-serve.py (gb300 GPU, bf16, tunnel 11437)
                        │                                            └─► ANEEmbedBar (m5, 127.0.0.1:11435, w8a16)
                        ├─ < 32 texts: whole, to whichever of gb300 / ANE has fewer requests in flight
                        ├─ /rerank ─► gb300's BAAI/bge-reranker-v2-m3 (multilingual); gb300 down: given order, score 0
                        └─ /v1/chat/completions (fact extraction) ─► dispatched to workers with free slots:
                              gb300 qwen3.8-27b vLLM (tunnel 11510, 24 slots) · m5 Ollama qwen3.6 on the GPU (4 slots)
```

- **One vector space.** Both engines serve `unsloth/embeddinggemma-300m`, the model relic5 already mixes across
  engines (`unsloth--embeddinggemma-300m@806f5f90`). Measured 2026-10-26 on 259 m5 texts: cosine between gb300 bf16 and
  ANE w8a16, min 0.9976, p05 0.9983, median 0.9991. Each falls back to the other.
- **Prompts in the text**, as relic5 does: Hindsight's `EMBEDDINGS_QUERY_PREFIX="task: search result | query: "` and
  `PASSAGE_PREFIX="title: none | text: "`; the engines take raw text.
- **The LLM is split** (Nat: "workers and dispatch to do many concurrent / parallel"): Hindsight's 32 worker slots
  call the router's `/v1/chat/completions` (model `relic-llm`); each call goes to the backend with the most free
  slots and is retried on the other if it fails. gb300 is shared and busy (a 27B call took ~127 s under load), so
  m5's own GPU adds a second, independent worker. `/health` shows `llm`: slots busy, calls, errors, average seconds.
- **The LLM is ours.** gb300's `glm-5.3-flash` (another user's vLLM) answered 500 to everything on 2026-10-26, so the
  profile uses nazt's `qwen3.8-27b` (32k context, `REASONING_EFFORT=none`, `RETAIN_MAX_COMPLETION_TOKENS=8192`).
- **Reranker:** `tei` through the router. The default FlashRank model (ms-marco-MiniLM) is English-only; much of the
  history is Thai. Example: for a Thai question, a Thai answer scored 0.92, the English one 0.68, an unrelated line 0.00002.
- **Nothing starts by itself** (m5 is manual): `embed/start.sh` brings everything up; the hindsight daemon stops
  itself when idle. The profile is `~/.hindsight/profiles/relic.env` (0600).

## Use it

```sh
embed/start.sh                                   # gb300 server, tunnel, router, daemon (skips what is up)
relic5 hindsight top                                # live TUI (relic-scan's look): bank, documents/min sparkline,
                                                 # queue + ETA, every worker's utilization bar and work, feeder log
relic5 hindsight status                             # documents, memories, queue with an ETA, which engine answered
relic5 hindsight import <session> [...] [--wait]    # a relic5 session's user/assistant turns, queued (async)
relic5 hindsight recall "what did we decide about X" [--limit 10] [--json]
relic5 hindsight retain "a fact" [--context C]
relic5 hindsight import --since 30d [--min-events 6] [--max N] [--wait]   # a window, newest first; skips imported ones
```

**Small batches** (Hindsight embeds ~5 facts a call) go whole to the engine with fewer requests in flight, so its 32
workers spread over gb300 and the ANE (48 concurrent calls: ANE 125 texts, gb300 121, 0 errors). Before this, all of
Hindsight's embedding ran on the ANE while gb300's embed server sat idle. The router's listen queue is 256 (the
default 5 refused connections under that load). Restarting the router drops the LLM calls in flight; Hindsight retries.

**Split:** a big batch goes to both engines at once, sized by their measured speed (EWMA, in `/health` as `rate`).
Measured 2026-10-26: 3,000 texts at 1,130 texts/s split, against 1,032 on gb300 alone. The ANE adds about 100 texts/s
beside gb300's 1,100; for small batches the ANE on m5 is the quicker answer (no network round trip).

**Throughput:** Observations are on (`HINDSIGHT_API_ENABLE_OBSERVATIONS=true`). Hindsight's `WORKER_MAX_SLOTS` (default 10) caps parallel retains; the profile sets 32, with
`RETAIN_LLM_MAX_CONCURRENT=32`, which the qwen3.8-27b vLLM on gb300 absorbs.

`import` reads the session from the hub (`/api/conversation`), keeps user and assistant turns, and sends blocks of
about 3,000 characters (Hindsight's retain chunk), each its own document `<session>#<n>` with the session in
`metadata.relic5_session` and the first turn's time as its timestamp. A re-import replaces the blocks.

**ETA:** `status` divides what is still queued (the child `retain` operations' items) by the rate of the ones finished
in the last hour. It says "unknown" until two have finished. First run, 2026-10-26: session 0f7f08a8 (370 turns) →
90 blocks → 607 memories in about 1.5 minutes, 27.6 blocks a minute, LLM-bound on gb300.

## Workers: the dispatcher's registry

The router is the dispatcher; its workers live in `~/.config/relic5/workers.json` (`embed`, `llm`, `rerank`), written
from defaults on first start and re-read when it changes. Add or remove one while it runs:

```sh
relic5 hindsight workers                                    # every worker: up, busy x/slots, util (last minute),
                                                         # calls / texts / tokens per minute and in total, errors, avg s
relic5 hindsight workers add llm gb300-b http://127.0.0.1:11520/v1/chat/completions --model qwen3-30b --slots 16
relic5 hindsight workers add embed mba http://100.85.98.2:11435 --model embeddinggemma:ane-w8a16 --batch 64
relic5 hindsight workers rm embed mba
```

A new embed worker must answer a 768-dimension vector before it is accepted (one vector space). Utilization is the busy
share of the last 60 s: time spent in requests (running ones counted so far) / (60 s x slots).

### Which model, which worker (measured 2026-10-26)

Fact extraction, one real Hindsight retain prompt (7.4k-character system prompt, a 2.75k-character Thai vault note,
JSON schema output):

| model | time | result |
|---|---|---|
| m5 Ollama gemma3:1b | 4.4 s | valid JSON, 1 fact: too thin |
| m5 Ollama llama3.2:1b | 28.8 s | broken JSON |
| m5 Ollama gemma3:4b | timed out | m5's GPU was busy |
| m5 Ollama qwen3.6 (36B MoE) | 79.7 s | 8 facts |
| gb300 qwen3.8-27b (vLLM) | 23.7 s | 9 facts |

Tiny models do not make a usable first pass, and m5's GPU as an LLM worker gave ~4% of the LLM work while saturating
the GPU. So the fast first pass is **embed-first** (chunks, no LLM) and the facts come from gb300's 27B later; m5's GPU
moved to embedding: Ollama `embeddinggemma:latest` on it matches the ANE (256 vault texts: cos min 0.9980, p05 0.9982,
median 0.9986), registered as embed worker `m5-gpu`. gb300's embed server hits CUDA OOM while other users fill its GPU
(254/256 GB); the router rests it 30 s after each error, and while the GPU stays full it is out of the embed pool
(`relic5 hindsight workers rm embed gb300`; back with `relic5 hindsight workers add embed gb300 http://127.0.0.1:11437
--model unsloth/embeddinggemma-300m --batch 4096`). It still reranks.

Small batches go to the worker that would finish first, (requests in flight + 1) / measured texts per second, so the
faster one takes proportionally more: by raw in-flight count with ties to the first listed, the ANE took 2,464 calls
and the faster m5 GPU 535 (34% busy).

## Everything relic5 holds (Nat, 2026-10-26: "memory first then vault, git, thinking, then sessions")

```sh
relic5 hindsight import --source memory     # then vault, git, thinking; then: relic5 hindsight import --since 3650d
```

`embed/hindsight-source.py` runs on the hub and reads `~/relic5/parts`; `embed/hindsight-import.py` on m5 queues
its items, newest first, while the bank has fewer than 40 open operations, and records each queued document in
`~/.cache/relic5/hindsight-<bank>-<source>.done`, so a stopped run resumes. Tags: `relic5`, `source:<name>`.

| source | what one item is | items (2026-10-26) | ~blocks |
|---|---|---|---|
| memory | one memory note (.md), MEMORY.md indexes skipped | 9,495 | 9.5k |
| vault | one ψ vault note, its chunks joined | 82,850 | 223k |
| git | our commits in one repo on one day (40 a block) | 15,348 | 6.3k |
| thinking | a session's thinking, ~3,000 characters | 13,178 | 11.6k |
| sessions | user + assistant turns, ~3,000 characters | 73,657 sessions | ~400k |

Tool output stays out: 3.97M rows of command output, little to learn as facts. At 88 blocks a minute (qwen3.8-27b on
gb300 is the limit) memory takes ~2 h, the vault ~42 h, git and thinking ~3 h each, sessions ~3 days.

## Backup

```sh
relic5 hindsight backup        # bin/relic5-hindsight-backup
```

`pg_dump -Fc -Z 3` of the hindsight-embed daemon's pg0 Postgres into relic5's backup volume (`bin/relic5-backup-volume`,
the case-sensitive sparse bundle on m5) at `<volume>/hindsight/hindsight-<profile>-<stamp>.dump`, written as `.partial`
and renamed only on success, then read back with `pg_restore --list`. The profile file (0600) and `workers.json` are
copied beside it; the newest 3 dumps stay. By hand, no timer. First run 2026-10-26: a 26 GB bank → 6.9 GB dump,
202 archive entries, 183 s.

Restore (the daemon stopped, into a fresh pg0 instance or the same one):

```sh
hindsight-embed daemon stop
D=~/relic5-backup-cs/hindsight/hindsight-relic-<stamp>.dump
PGPASSWORD=hindsight ~/.pg0/installation/18.1.0/bin/pg_restore -h 127.0.0.1 -p 5432 -U hindsight -d hindsight --clean --if-exists "$D"
```

## Who owns what

- `embed/gb300-serve.py`, `embed/embed-router.py`, `embed/start.sh`, `relic5 hindsight` (`cli/src/memory.rs`): relic5.
- Hindsight itself: vectorize-io/hindsight (`uv tool install hindsight-embed`), unchanged.
- ANEEmbedBar: ane-oracle `tools/ane-embed-app`, unchanged. Its own worker pool refuses gb300 on purpose (a remote must
  report the same CoreML `vector_space_identity`), so the mixing happens in the router, backed by the parity numbers above.
