# HINDSIGHT: relic5's history as memory, embedded on gb300 and the ANE

Nat, 2026-10-26: "install hindsight and use gb300 to embed? make it compat work with ane on m5 too?", "if huge can we
go gb300 first?", "can we add more to make our cli compat with hindsight?". relic5 keeps every turn; Hindsight
(vectorize-io/hindsight, the `hindsight-embed` daemon on m5) keeps what was learned from them: facts, entities,
observations, mental models.

## The pieces

```
relic5 memory …  ──►  hindsight-embed daemon (m5, 127.0.0.1:8888, profile "relic", its own pg0 database)
                        │ LLM (fact extraction): qwen3.8-27b, vLLM on gb300, through the tunnel (127.0.0.1:11510)
                        │ embeddings + rerank ▼
                      embed/embed-router.py (m5, 127.0.0.1:11436)
                        ├─ ≥ 32 texts: split by speed, both at once ─► embed/gb300-serve.py (gb300 GPU, bf16, tunnel 11437)
                        │                                            └─► ANEEmbedBar (m5, 127.0.0.1:11435, w8a16)
                        ├─ < 32 texts: ANE first, gb300 if it fails
                        └─ /rerank ─► gb300's BAAI/bge-reranker-v2-m3 (multilingual); gb300 down: given order, score 0
```

- **One vector space.** Both engines serve `unsloth/embeddinggemma-300m`, the model relic5 already mixes across
  engines (`unsloth--embeddinggemma-300m@806f5f90`). Measured 2026-10-26 on 259 m5 texts: cosine between gb300 bf16 and
  ANE w8a16, min 0.9976, p05 0.9983, median 0.9991. Each falls back to the other.
- **Prompts in the text**, as relic5 does: Hindsight's `EMBEDDINGS_QUERY_PREFIX="task: search result | query: "` and
  `PASSAGE_PREFIX="title: none | text: "`; the engines take raw text.
- **The LLM is ours.** gb300's `glm-5.3-flash` (another user's vLLM) answered 500 to everything on 2026-10-26, so the
  profile uses nazt's `qwen3.8-27b` (32k context, `REASONING_EFFORT=none`, `RETAIN_MAX_COMPLETION_TOKENS=8192`).
- **Reranker:** `tei` through the router. The default FlashRank model (ms-marco-MiniLM) is English-only; much of the
  history is Thai. Example: for a Thai question, a Thai answer scored 0.92, the English one 0.68, an unrelated line 0.00002.
- **Nothing starts by itself** (m5 is manual): `embed/start.sh` brings everything up; the hindsight daemon stops
  itself when idle. The profile is `~/.hindsight/profiles/relic.env` (0600).

## Use it

```sh
embed/start.sh                                   # gb300 server, tunnel, router, daemon (skips what is up)
relic5 memory status                             # documents, memories, queue with an ETA, which engine answered
relic5 memory import <session> [...] [--wait]    # a relic5 session's user/assistant turns, queued (async)
relic5 memory recall "what did we decide about X" [--limit 10] [--json]
relic5 memory retain "a fact" [--context C]
relic5 memory import --since 30d [--min-events 6] [--max N] [--wait]   # a window, newest first; skips imported ones
```

**Split:** a big batch goes to both engines at once, sized by their measured speed (EWMA, in `/health` as `rate`).
Measured 2026-10-26: 3,000 texts at 1,130 texts/s split, against 1,032 on gb300 alone. The ANE adds about 100 texts/s
beside gb300's 1,100; for small batches the ANE on m5 is the quicker answer (no network round trip).

**Throughput:** Hindsight's `WORKER_MAX_SLOTS` (default 10) caps parallel retains; the profile sets 32, with
`RETAIN_LLM_MAX_CONCURRENT=32`, which the qwen3.8-27b vLLM on gb300 absorbs.

`import` reads the session from the hub (`/api/conversation`), keeps user and assistant turns, and sends blocks of
about 3,000 characters (Hindsight's retain chunk), each its own document `<session>#<n>` with the session in
`metadata.relic5_session` and the first turn's time as its timestamp. A re-import replaces the blocks.

**ETA:** `status` divides what is still queued (the child `retain` operations' items) by the rate of the ones finished
in the last hour. It says "unknown" until two have finished. First run, 2026-10-26: session 0f7f08a8 (370 turns) →
90 blocks → 607 memories in about 1.5 minutes, 27.6 blocks a minute, LLM-bound on gb300.

## Everything relic5 holds (Nat, 2026-10-26: "memory first then vault, git, thinking, then sessions")

```sh
relic5 memory import --source memory     # then vault, git, thinking; then: relic5 memory import --since 3650d
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

## Who owns what

- `embed/gb300-serve.py`, `embed/embed-router.py`, `embed/start.sh`, `relic5 memory` (`cli/src/memory.rs`): relic5.
- Hindsight itself: vectorize-io/hindsight (`uv tool install hindsight-embed`), unchanged.
- ANEEmbedBar: ane-oracle `tools/ane-embed-app`, unchanged. Its own worker pool refuses gb300 on purpose (a remote must
  report the same CoreML `vector_space_identity`), so the mixing happens in the router, backed by the parity numbers above.
