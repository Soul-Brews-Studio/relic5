# Session-history apps: inventory and verdicts (2026-10-24)

Every app or tool the fleet built to collect, search, watch, serve or embed agent session history, sorted by
the job it does. Each one gets a verdict: **KEEP**, **MERGE into X** (port a named feature, then retire), or
**RETIRE**. Retiring means an archive notice in that repo's README. Nothing gets deleted. This file edits no other
repo.

## How the evidence was gathered (all read-only, on m5, 2026-10-24 about 08:50 +07)

- **Last commit / commits 30d**: `git -C <repo> log -1 --format=%cs [-- subdir]` and
  `git -C <repo> rev-list --count --since=2026-09-24 HEAD [-- subdir]`. Five repos were born inside the window, so
  their 30-day count is their whole history: relic5 (first commit 10-23), relic-extract (10-23), relic4-scan (10-22),
  agent-relic-v4 (10-22), agent-relic-v3 (10-02).
- **Sessions 30d**: the relic5 hub, `GET /api/sessions?since=2026-09-24&repo=<name>` on
  `white.follow-rankine.ts.net:8795`, field `total`. This counts top-level Claude sessions only. Subagents fold into
  `children`, and Codex sessions carry no repo key, so they are not counted. A count of 1 can be one long session with
  hundreds of commits, as with relic5 and relic4-scan. Every count was checked against the `*.jsonl` mtimes in
  `~/.claude/projects/*<name>*`, and the two sources agree.
- **MCP use**: `~/.claude.json` `mcpServers`, then real `tool_use` blocks in transcripts changed in the last 30 days
  (`fd --changed-within 30d -e jsonl ~/.claude/projects | xargs rg`), parsed with Python and filtered to
  `timestamp >= 2026-09-24`. Resident MCP processes were counted with `ps` (count and RSS).
- **Running**: `launchctl list` and `launchctl print` (run counts, last exit), `lsof -iTCP -sTCP:LISTEN` with each pid's
  cwd, `ps` for the apps, plus the job logs (`/tmp/relic-push.log`, `/tmp/relic-indexer.log`,
  `~/Library/Logs/relic-chain.log`) and the hub's `/api/status`, `/api/log?n=1000` and `/api/queries`.

### The facts the verdicts rest on

| fact | evidence |
|---|---|
| Agents still search through **relic3**, not relic5 | MCP tool calls since 09-24: relic3 **727** (664 `relic_search`), session-viewer 75, session-search 23, **relic5 15** (all from the relic5 and relic4-scan repos), jsonl-indexer 3, session-dream 1 |
| relic3's local index is stale | `~/.relic3/index` mtime 2026-10-15. BRIEF.md says the `relic_search` MCP reads this one |
| Skills hard-code the old servers | `~/.claude/skills/relic3/SKILL.md` and `ralph-dig/SKILL.md` call relic3. `day-diary/SKILL.md` calls `mcp__session-viewer`. No skill names relic5 |
| Legacy MCP servers cost memory in every session | resident right now: jsonl-indexer 82 procs / 2,252 MB, relic3 43 / 1,969 MB, session-search 44 / 1,115 MB, session-dream 37 / 427 MB, session-viewer 44 / 308 MB. About 6 GB in total. `relic5 mcp` had 0 processes |
| relic5 hub is live and fed by 3 machines | `/api/log`: pushes from m5 (84), white (68) and mba (62), plus 50 index runs, all `done`, between 10-23 14:25Z and 10-24 01:48Z. Index holds 1,100,435 rows and 1,015,946 + 83,991 vectors, 0 pending |
| Two pipelines feed white at once | relic3: `studio.soulbrews.relic-push` (every 5 min, 434 runs, rsync of raw transcripts to `white.local`) and `relic-indexer` (every 10 min, 216 runs, "indexer published 20261024T014746Z"). relic5: `studio.soulbrews.relic-chain` (every 10 min, last "SYNC OK text 869323 thinking 102247 tools 2002706" at 08:44) |
| RelicFeeder is up, but not as a LaunchAgent yet | pid 24384 since 10-23 23:54, running from `relic5/feeder/RelicFeeder.app` (build dir). `~/Library/LaunchAgents` has no feeder plist. The hub log shows `client: relic-feeder` status calls |
| relic5 embed still needs agent-relic-v4 | `src/relic5/worker.py:20` (`RELIC5_RELIC4` defaults to the v4 checkout) and `:50` (`from relic4.embed import remote_embed`) for gb300. The only `embed` jobs on the hub log are on `ane` (m5) |
| v3 Mac apps still run against relic3 | `Relic Studio.app` (pid 39668) and `RelicScanner.app` (39670), both opened at 08:28 today, from agent-relic-v3 `studio/` and `scanner/` |

These things were started by hand this morning (08:29 to 08:32), with no LaunchAgent loaded for any of them:
jsonl-oracle `app/lance` (:8094), `app/lance-py` (:8098) and `StructorTray`, session-viewer `webapp` (vite :5273),
and jsonl-indexer-mcp (:4321). They look like a side-by-side comparison, not daily use. The seven
`studio.soulbrews.structor.*` plists are on disk but not loaded.

Skipped as not session history: `indexer-pro` (vector indexing for arra-oracle-v3 knowledge bases),
`digger-node` (Drupal-shaped content store on a Worker), `indexer-pro-oracle` and `oracle-dig-ui-oracle` (oracle
identity repos with no app code). `relic-lessons` is the written record of four relic generations (book, CORE.md,
LESSONS.md). It is not an app. **KEEP** it as the reference.

---

## (a) Search history as a human (web / app / TUI)

| app | what it is | last commit | commits 30d | sessions 30d | in use now? | verdict |
|---|---|---|---|---|---|---|
| **relic5 web UI** (`web/`, served at `white…:8795/`) | React UI on the hub: Search, Live, Jobs, Queries, Store, Compare | 2026-10-24 | 61 (repo) | 1 (long, 4 children) | yes: hub serves it, dev vite on :5173 | **KEEP** (the one) |
| relic5 `tui` (`src/relic5/tui.py`) | terminal view of the hub (`/api/queries` etc.) | 2026-10-24 | (repo) | (repo) | CLI only | **KEEP** (same tool) |
| relic4-scan `serve` / `up` / `tui` | local `/map` and `/tree` on 127.0.0.1, terminal browser of one machine's parquet | 2026-10-24 | 127 | 1 | :8797 serves `site/`, :8795 local serves `site/public` (landing preview) | **KEEP**, scoped to the stand-alone product (no hub) |
| ARRA Relic Scan.app (`relic4-scan/desktop`) | public desktop build of relic-scan (v26.10.23) | 2026-10-24 | (repo) | (repo) | installed in ~/Applications, not running | **KEEP** (public product, not the fleet's search) |
| relic-extract `tui` / report | analyse report of the cut chunks | 2026-10-24 | 42 | 1 | report served on :18733 and :8798 from `~/.relic-extract/report` | **KEEP** (QA view for extract, not search) |
| agent-relic-v3 `app/` (RelicBar + RelicMonitor) | menu-bar history panel over the relic3 CLI | 2026-10-04 | 6 | in v3's 22 | not running | **RETIRE** (CLIProcess.swift, JSONLJobTail.swift already reused by RelicFeeder, docs/RELICFEEDER.md) |
| agent-relic-v3 `desk/` (+ `desk/ui`) | three-column web workspace: worktrees, transcripts, history | 2026-10-03 | 1 (ui) | in v3's 22 | no | **RETIRE** |
| agent-relic-v3 `full-app/` | execution host + Mac/iPad clients (runs Claude/Codex) | 2026-10-04 | 10 | 19 (worktree `wt/full-relic-app…issue160`), last 10-09 | no | **RETIRE** (an agent runner, not history; nothing to port into relic5) |
| agent-relic-v3 `chat-app/` | SwiftUI chat client for the #161 backend | 2026-10-04 | 8 | in v3's 22 | no | **RETIRE** |
| session-viewer (Soul-Brews-Studio) | Swift app + CLI + React webapp + Worker demo | 2026-09-01 | 0 | 0 | webapp vite :5273 (hand-started today) | **RETIRE** |
| digger-oracle `ψ/lab/session-viewer` | the original of the above; its binary is the live MCP | 2026-08-28 | 0 | digger-oracle 7 (repo-wide) | MCP yes (see d) | **MERGE into relic5** (see d), then RETIRE |
| jsonl-oracle `app/ui`, `app/lance`, `app/lance-py` (Structor) | PocketBase week index + LanceDB replica + admin UI | 2026-09-11 | 0 | 0 | lance :8094, lance-py :8098 (hand-started today) | **RETIRE** (layout already ported: relic5 commit 9485b8d) |
| relic-ui | browser client for agents-relic `relic serve` | 2026-09-23 | 0 | 0 | no | **RETIRE** |
| lance-indexer | LanceDB indexer with block search, web screens, Worker demo | 2026-09-01 | 0 | 0 | no | **RETIRE** |
| session-jsonl-observatory | indexer + inspector plan/prototype | 2026-09-03 | 0 | 0 | no | **RETIRE** |
| jsonl-lens | `rg` over raw jsonl, no index | 2026-08-15 | 0 | 0 | no | **RETIRE** (`relic5 tail` and search cover it) |

## (b) See sync / health of the collection

| app | what it is | last commit | commits 30d | sessions 30d | in use now? | verdict |
|---|---|---|---|---|---|---|
| **relic5 hub status** (`/api/status`, `/api/log`, web Store/Jobs/StatusBar, `relic_status`) | watermarks, freshness per machine, jobs, versions, warnings, doors | 2026-10-24 | 61 | 1 | yes: 18 `relic_status` calls in the last 20 queries, 2 from `relic-feeder` | **KEEP** (the one) |
| `relic-chain` SYNC check (`~/.local/bin/relic-chain`) | extract counts vs hub counts per stream | n/a (script) | n/a | n/a | yes: "SYNC OK" 08:44 | **KEEP** until RelicFeeder carries it, then fold in |
| RelicFeeder panel (`relic5/feeder`) | menu-bar freshness card + last jobs from the hub | 2026-10-23 | 3 | (relic5) | yes, pid 24384 | **KEEP** (Mac front for b and c) |
| Relic Studio.app (agent-relic-v3 `studio/`) | Smart Scan / Embedding / Banks / Health over relic3 | 2026-10-05 | 6 | in v3's 22 | **running** (08:28) | **RETIRE** (shows relic3 state, which is not what agents should read) |
| RelicScanner.app (agent-relic-v3 `scanner/`) | Smart Scan, Embedding, Banks, Health, Jobs over relic3 | 2026-10-05 | 6 | in v3's 22 | **running** (08:28) | **RETIRE** |
| StructorTray (jsonl-oracle `app/tray`) | tray for the Structor services | 2026-09-10 | 0 | 0 | running from `.build/release` (08:32), plist not loaded | **RETIRE** |
| jsonl-liveness | which sessions are live (file mtime vs message time), React UI | 2026-09-12 | 0 | 0 | no | **RETIRE** (relic5 Live view: `web/src/views/LiveView.tsx`) |

## (c) Feed the hub from a Mac (scan / extract / push)

| app | what it is | last commit | commits 30d | sessions 30d | in use now? | verdict |
|---|---|---|---|---|---|---|
| **relic4-scan** (`relic-scan run`) | Rust: find every agent home, parse, `meta/sessions.parquet`, one parquet a month | 2026-10-24 | 127 | 1 | yes, step 1 of relic-chain | **KEEP** |
| **relic-extract** (`relic-extract run`) | Rust: pick streams, dedupe, cut chunks with a stable key, after-hook push | 2026-10-24 | 42 | 1 | yes, step 2 of relic-chain | **KEEP** |
| **relic5 `bin/relic5-push`** | rsync parts + meta to `white…:/home/nat/relic5/parts/<machine>` | 2026-10-24 | (repo) | (repo) | yes, "relic5 push m5 … rc=0 2s" in relic-chain.log | **KEEP** |
| **RelicFeeder** (`relic5/feeder`) | SwiftUI menu bar that runs the chain and shows the hub card | 2026-10-23 | 3 | (repo) | yes, but from the build dir, no LaunchAgent | **KEEP** (Mac front). Install it as the LaunchAgent, then unload relic-chain after a day (per memory note, ask first) |
| `studio.soulbrews.relic-chain` LaunchAgent | 10-min loop: scan, extract, push, SYNC check | n/a | n/a | n/a | yes (loaded, last rc 0) | **KEEP until RelicFeeder is the LaunchAgent**, then unload |
| agent-relic-v3 `hub/` (`push.sh`, `indexer.sh`) + LaunchAgents `relic-push`, `relic-indexer`, `relic-embed-tunnel` | relic3 hub: raw transcript mirror to `white.local`, index on m5, publish | 2026-10-07 | 11 | in v3's 22 | **yes**: 434 + 216 runs, last 08:49 / 08:47 | **UNLOADED 2026-10-24 09:25** (Nat): `relic-push` and `relic-indexer` stopped on m5, plists kept at `/tmp/studio.soulbrews.relic-{push,indexer}.plist.bak` (reload: `launchctl load -w ~/Library/LaunchAgents/<name>.plist`). No new relic3 generation reaches white; the existing `~/.relic3-gens` (81 GB, last generation 20261024T020854Z) stays until Nat decides, with a copy offered first. `relic-embed-tunnel` untouched. relic3's MCP still answers, from that frozen index |
| agent-relic-v3 `scanner/` (as a feeder) | INDEX NOW / EMBED buttons for relic3 | 2026-10-05 | 6 | in v3's 22 | running app | **RETIRE** (see b) |
| jsonl-oracle Structor `watch-local` / `watch-kvmlab1` | week-stamped PocketBase intake | 2026-09-11 | 0 | 0 | plists not loaded | **RETIRE** |
| agents-relic (v1), agent-relic-v2, agent-relic-v2.1 | LanceDB-per-repo (v1), y/m/tenant layout (v2, v2.1). `relic` on PATH is v2.1 | 2026-10-01 / 09-25 / 10-01 | 1 / 1 / 24 | 0 / 0 / 0 | CLI installed (`~/.bun/bin/relic` → agent-relic-v2.1), no job | **RETIRE** all three (`tail` and `handoff` already in relic5, RELIC3-COMPARE.md "Reading") |

## (d) Agent access (MCP)

| app | what it is | last commit | commits 30d | sessions 30d | in use now? | verdict |
|---|---|---|---|---|---|---|
| **relic5 MCP** (`relic5 mcp` stdio shim → hub `POST /mcp`) | the five relic3 tools on the hub, month store, 3 machines | 2026-10-24 | 61 | 1 | registered top-level. **15 calls**, 0 resident procs | **KEEP** (the one), but it is not yet the one agents use |
| relic3 MCP (agent-relic-v3 `src/`) | the same five tools over the relic3 index | 2026-10-07 | 335 (src) | 22 | **727 calls**, 43 procs / 1.97 GB. Index stale since 10-15 | **MERGE into relic5**: the 5 gaps below, then switch the skills, then RETIRE |
| session-viewer MCP (digger-oracle lab binary) | FTS5 trigram search, read_context, topics, graph | 2026-08-28 | 0 | 7 (digger-oracle) | **75 calls** from other oracles (floodboy-ios, herald, pigment, DustBoy). Index `sessions.db` touched 10-21. `day-diary` skill depends on it | **MERGE into relic5** (Thai-substring check), then RETIRE |
| session-search MCP (digger-oracle lab, bun) | horizon buckets over session-viewer's index | 2026-08-28 | 0 | (above) | 23 calls, last 10-14. 44 procs / 1.1 GB | **RETIRE** (relic5 has horizons and widening) |
| session-dream MCP (2sep lab 05) | LanceDB + Apple NLContextualEmbedding, `dream`, `compare_horizons` | 2026-09-02 | 0 | 0 | 1 call (10-05). Index frozen 2026-09-02. 37 procs / 427 MB | **RETIRE** |
| jsonl-indexer MCP (4sep lab 01) | LanceDB + nlembed lab server | 2026-09-03 | 0 | 0 | 3 calls (last 10-05, `.mcp-calls.jsonl` same date). **82 procs / 2.25 GB** | **RETIRE first**: heaviest, least used |
| agent-relic-v4 `mcp_server.py` / `relic4 serve` | relic4 core + API + MCP | 2026-10-23 | 26 | 1 | `relic4 serve` up on 127.0.0.1 + 100.111.101.21, ports 8791/8792, since 10-23 12:02. Not in `~/.claude.json` | **MERGE into relic5** (embed, see e), then RETIRE and stop the serve |

## (e) Embed

| app | what it is | last commit | commits 30d | sessions 30d | in use now? | verdict |
|---|---|---|---|---|---|---|
| **relic5 `embed` worker** (`src/relic5/worker.py`, `vec.py`) | client-side embed: policy gb300 for a backlog > 50k, ANE for increments, parity probe, ships shards | 2026-10-24 | 61 | 1 | yes: `embed-m5` jobs "24,056 chunks on ane", "9,156 chunks on ane". Hub reports 0 pending | **KEEP** (the one) |
| agent-relic-v4 `src/relic4/embed.py` | gb300 `remote_embed`, key-addressed vector cache (seeded relic5's 1.03 M vectors) | 2026-10-23 | 26 | 1 | used **by import** from relic5 `worker.py:50` | **MERGE into relic5**: copy `remote_embed` + `_ssh` (embed.py:110–152), then RETIRE |
| agent-relic-v3 `src/verbs/embed.ts` + `relic-embed-tunnel` LaunchAgent | relic3 embed via the m5 MLX engine, tunnel to `white.local:11438` | 2026-10-07 | (src) | (v3) | tunnel loaded (pid 3107) | **RETIRE** with relic3 |
| session-dream / jsonl-indexer `nlembed` | Apple on-device 512-d embedder labs | 2026-09-03 | 0 | 0 | only through their MCPs | **RETIRE** |
| ANE engine (ane-oracle `ANEEmbedBar`, :11435) | on-device embedder relic5 calls for increments | (other repo) | n/a | n/a | yes, LaunchAgent `studio.soulbrews.ane-embed` | **KEEP** as an engine. Not a session-history app, so out of scope here |

---

## Recommendation

### One tool per job

- **(a) human search**: the relic5 hub web UI at `http://white.follow-rankine.ts.net:8795/` (plus `relic5 tui`).
  relic4-scan's `serve`/`tui` and ARRA Relic Scan.app stay as the **stand-alone public product** for someone without
  a hub. They are not a second fleet search.
- **(b) health**: the relic5 hub status (`/api/status`, web Store/Jobs, `relic_status`), shown on each Mac by
  **RelicFeeder**. Today relic-chain's SYNC line does the real check. Fold that check into RelicFeeder's pass
  (`feeder/Sources/FeederCore/Checks.swift`) before relic-chain is unloaded.
- **(c) feed from a Mac**: `relic-scan run` (relic4-scan), then `relic-extract run`, then `bin/relic5-push`, driven by
  **RelicFeeder**. The evidence disagrees with the plan in two places:
  1. RelicFeeder runs from the build dir with no LaunchAgent, so `relic-chain` is still the scheduled feeder.
  2. ~~relic3's `relic-push` + `relic-indexer` still write to white every 5 and 10 minutes.~~ Unloaded 2026-10-24
     09:25 (Nat's decision): relic3's index on white is frozen at 20261024T020854Z.
  These are three schedulers for one job. End state: one RelicFeeder LaunchAgent per Mac. Unload relic-chain a day
  after that (memory note, ask Nat). Unload relic3's jobs only after (d) is done.
- **(d) agent access**: **relic5 MCP**, as expected. But the evidence says agents have **not moved**: relic3 has 727
  calls against relic5's 15, and relic3 is answering from an index 9 days stale. The switch is a config and skill
  change, not code:
  1. Rewrite `~/.claude/skills/relic3/SKILL.md` and `ralph-dig/SKILL.md` to call `mcp__relic5__*` (same tool names
     and schemas: BRIEF.md point 4).
  2. Point `day-diary/SKILL.md` at relic5.
  3. Remove the `relic3`, `session-viewer`, `session-search`, `session-dream` and `jsonl-indexer` entries from
     `~/.claude.json`. That frees about 6 GB of resident MCP processes.
- **(e) embed**: the **relic5 embed worker**, as expected. One dependency remains: gb300 runs through
  agent-relic-v4's code (`worker.py:20,50`). Until that is ported, v4 cannot be archived.

### Merge: what to port into relic5

| from | feature | where (source) | into relic5 | size |
|---|---|---|---|---|
| agent-relic-v4 | gb300 `remote_embed` + `_ssh` | `src/relic4/embed.py:110-152` | `src/relic5/worker.py` `gb300()` (drop the `RELIC5_RELIC4` subprocess at `:20`, `:50`) | S |
| agent-relic-v3 | quarantine of rows dated before 2023-01-01 or after now+2d | `src/contracts/time.ts:53-55` (`EARLIEST_MS`, `weekOrQuarantine`), `src/index/writer.ts:128-131` | `src/relic5/parts.py` (month of a row) | S |
| agent-relic-v3 | generic-query warning | `src/search/generic.ts:186` (`genericWarning`), called at `src/verbs/search.ts:205` | `src/relic5/search.py`, as a `warning` field on the result | S |
| agent-relic-v3 | `read`: whole transcript, paged, `--prose` | `src/verbs/read.ts:7` | `relic_show` paging is there. Add a `read` verb to `cli.py` and `mcp.py` | S |
| agent-relic-v3 | session lookup by name | `src/read/resolve.ts:122` (`filesForTarget`), `src/read/name.ts:29` (`nameOf`) | `src/relic5/query.py` `session()` | S |
| agent-relic-v3 | gc dry-run report of reclaimable bytes | `src/verbs/gc.ts:29` | `src/relic5/gc.py` (it already lists foreign usage, 2026-10-24) | M |
| digger-oracle session-viewer | Thai **inside-word** match. Its trigram index is "the only thing here that finds Thai inside words" | `ψ/lab/session-viewer/Sources/SessionViewerCore/MCP.swift:78-87` | **verify first**: relic5 uses ICU tokens (`src/relic5/fts.py:1,20`). Add Thai-substring cases from session-viewer's eval (`Sources/SessionViewerCore/Eval.swift`) to `tests/eval/semantic.json`. Port a trigram fallback only if ICU misses them | S–M |
| relic-chain script | SYNC check: extract counts vs hub per stream | `~/.local/bin/relic-chain` (the `want`/`got` loop) | `feeder/Sources/FeederCore/Checks.swift` | S |

Already ported, so nothing more to carry: relic3's five MCP tools, `tail`, `handoff`, `recap` and `pending`
(RELIC3-COMPARE.md); Structor's admin layout (relic5 commit 9485b8d); v3 `CLIProcess.swift` and `JSONLJobTail.swift`
(RelicFeeder); v4 FTS settings (`fts.py:20`); v3 hub push and serve unit (README "Pieces").

Not ported on purpose: session-viewer topics (`promote_topic`, `trace_topic`, …), `session_graph`, session-dream
`dream` and `compare_horizons`. None of them was called in 30 days (the per-tool counts show only
`search_sessions`, `read_context`, `index_status`, `list_sessions` and `describe_tool`).

### Retire: archive notice in README (list only, these repos are not edited here)

Do these in order. Each later step depends on the earlier ones.

1. **Now** (no users, no jobs): agents-relic, agent-relic-v2, agent-relic-v2.1 (also `bun remove -g agents-relic`
   to drop the `relic` CLI, ask first), relic-ui, jsonl-lens, jsonl-liveness, lance-indexer,
   nat-build-with-oracle/session-jsonl-observatory, Soul-Brews-Studio/session-viewer and Soul-Brews-Studio/session-search
   (the extracted copies; the live MCP binary is the digger-oracle lab), jsonl-oracle (Structor: `app/`, tray, lance,
   lance-py, ui, plus the seven unloaded `studio.soulbrews.structor.*` plists).
2. **With the `~/.claude.json` cleanup in (d)**: nat-build-with-oracle/4sep-fri2026-oracle `ψ/lab/01-jsonl-indexer-mcp`,
   nat-build-with-oracle/2sep-wed2026-oracle `ψ/lab/05-session-lance-mcp`, digger-oracle `ψ/lab/session-search`. Put
   the notice in each lab's README. These are oracle repos, so only the lab is retired.
3. **After the skills point at relic5 and the Thai check passes**: digger-oracle `ψ/lab/session-viewer` (lab README
   notice).
4. **After the v3 merge rows land and agents have used relic5 for a week**: agent-relic-v3, whole repo: `src/`, `hub/`,
   `app/`, `scanner/`, `studio/`, `desk/`, `full-app/`, `chat-app/`. Unload `relic-push`, `relic-indexer` and
   `relic-embed-tunnel`, and quit Relic Studio.app and RelicScanner.app (ask first). relic5 already reads relic3 links
   through `resolve/relic3.parquet`, so old `relic3://` ids keep working.
5. **After `remote_embed` is in relic5**: agent-relic-v4. Stop `relic4 serve` on :8791/:8792 (ask first).

Keep: relic5 (hub, web, tui, MCP, embed, feeder), relic4-scan (incl. ARRA Relic Scan.app and its public site),
relic-extract, relic-lessons (docs).

### Side notes found on the way

- `~/.local/share/relic-push.sh` defaults to `HUB=white.local`, and the `relic-embed-tunnel` plist targets
  `white.local`. That is the LAN name, not the tailnet name `white.follow-rankine.ts.net`. Both go away when relic3
  retires. Until then they are the only parts of the relic chain off tailscale.
- The local `127.0.0.1:8795` is relic4-scan's landing preview (`python -m http.server --directory site/public`). It
  shares the hub's port number, so a local test of `relic5 serve` on 8795 would collide with it.
- Hub session counts skip Codex sessions (`repo` was null on all 161 Codex sessions among the 500 newest the hub returned for the window). A
  `repo` derived from Codex's `session_meta.cwd` in relic-scan meta would fix that.
