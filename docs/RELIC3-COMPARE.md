# relic3 vs relic5, feature by feature (2026-10-23)

relic3 = agent-relic-v3 @9f0bdb5 (`relic3 --help`, src/, the study in this session). relic5 = this repo.
Gap: **none** (at parity or better), **port** (worth bringing), **later**, **no** (deliberately different).

## Storage and publishing

| feature | relic3 | relic5 | gap |
|---|---|---|---|
| unit | ISO week, sealed + one open week | Bangkok month, sealed + the open month | no (Nat: month) |
| machines | one hub mirror of each machine's transcripts | parts pushed per machine, folded by msgkey | none |
| publish | run files, `_manifest/current` rename | per-month manifest, `current.json` rename, generations kept 3 | none |
| quarantine | rows dated before 2023-01-01 or after now+2d kept apart | not checked | port (S) |
| lossless archive of transcripts | `archive scan/list/verify/restore/seal` | extracted text only; raw transcripts not copied (Nat to decide) | later |
| gc | dry-run report of reclaimable bytes | generations pruned to 3, no report | port (M, with a no-sole-copy guard) |

## Search

| feature | relic3 | relic5 | gap |
|---|---|---|---|
| BM25 | LanceDB FTS, ICU, no stem, no stop words | the same settings, history/open per layer | none |
| term logic | any term matches, ranked ("longer queries return 11x more hits") | the same, plus an exact-phrase pass ranked first (positions in the index): known-item recall@10 0.875 vs relic4 0.845 vs relic3 0.695 | none (better) |
| horizon widening | 7d → 15d → 1m → 3m → archive until 10 hits | the same, the cursor pins it | none |
| fold of resumed copies | (ts, role, text) | the same, plus chunk key | none |
| prose before tools | yes | yes | none |
| sort newest | `--sort newest` (top 600 by ts) | `sort=newest` | none |
| generic-query warning | when every term is common | no | port (S) |
| semantic | separate mode, never blended (measured: FTS 0.890 vs 0.600 known-item; semantic 0.140 vs 0.046 paraphrase) | separate mode; hybrid RRF opt-in, measured worse on paraphrase (1/6 vs 2/6) | none: keep it opt-in, score per query type |
| query embedding | the hub calls an engine (tunnel to m5; down today) | the client embeds (`relic5 mcp` shim), the hub embeds nothing | no (better: no tunnel) |
| engine parity | `--also` engine admitted at cos median ≥ 0.998, min ≥ 0.99 | `relic5 embed --probe`: MPS vs stored, min 0.998 | none |
| ANN | IVF_PQ from 65,536 vectors, used at 20,000+, recall@10 0.90, ~20x faster | exact flat scan | port (M), measure recall first |
| short texts | not embedded under 24 chars | not searched by vector under 80 chars (measured) | none |
| filters | repo, bank, org, project, dir, worktree, path, tier, source, cwd, role, via/chat/from_user | repo, session, role, tier, cwd, branch, title, since/until/horizon, with | via/chat/from_user: when relic-scan carries channel fields |
| ephemeral paths | flags /tmp, scratchpad, claude-<pid> in hits | `ephemeral` on every hit | none |

## Reading

| feature | relic3 | relic5 | gap |
|---|---|---|---|
| show | uid / relic3:// / path+seq, neighbours by seq, the raw source line | msgkey / relic5:// / session+seq, neighbours by ts across months, no raw line | raw line: later (no transcripts on the hub) |
| old links | relic3:// and 40-hex uids | resolved through resolve/relic3.parquet (7.72 M uids): msgkey, then (session, ts), then the nearest message of the session, ψ notes by path; 12/12 real links from the history placed (2026-10-23) | none |
| session | prefix or name, transcripts, subagent tree, neighbours, `--resume` | prefix, subagents, counts, months, cwd/branch/version, the resume line | name lookup (S) |
| session names | host title, else first user text (name.ts rules) | the same (title from relic-scan meta, rules 1, 3–6) | none |
| read | whole transcript, paged | `relic_show` paging by seq | port `read` (S) |
| tail | last N exchanges; `--handoff` paste-ready block for /new | `tail` (newest as they land, all machines) and `handoff` | none |
| recap | what happened: user turns, tools, files edited, how it ended | `recap` | none |
| pending | on disk but not indexed | `pending` (stale months, chunks without vectors, push lag) | none |

## Operations

| feature | relic3 | relic5 | gap |
|---|---|---|---|
| status | watermarks, stale hours, quarantine, jobs, warnings | watermarks per lane, freshness per machine, jobs, versions, doors | none (quarantine: see above) |
| jobs log | logs/jobs.jsonl JobEvent | the same format; index, index-vectors, push | none |
| exit codes | 0 ok, 1 error, 2 usage, 75 locked, 130 cancelled | the same, plus 3 = parity refused (embed) | none |
| auth | token for non-loopback | loopback + Nat's tailnet need none; hashed, rotating tokens | none |
| UI | native Mac app (RelicBar) | web UI on the hub: Overview, Live, Jobs, Search, Compare | none |
| MCP | stdio, five tools | HTTP on the hub + stdio shim, the same five tools | none |
