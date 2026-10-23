# relic5: the brief (from relic4-scan, pane w11:p1 on m5, 2026-10-23)

## What Nat asked for

> "I DO NEED A SERVER THAT STORE MY WHOLE EXTRACTED HISTORY AND EMBEDDED STUFF AND DO SEND MORE OR IMPORT running on
> white server on vpn and we connect, do really like relic3."
> "this should be relic5? but bring code from relic3?"

One server on white keeps every machine's extracted history and its vectors. Each machine sends what is new; old data
is imported once; every machine searches and reads through it over tailscale, the way relic3's hub worked.

```
 m5 / mba / white / …                      white (white.follow-rankine.ts.net, tailscale)
 relic-scan ─► relic-extract ─► relic5 push ──►  relic5 hub ─► embed (gb300 · m5 MLX · white CPU)
 relic3 weeks, jsonl-truth ─► relic5 import ──►      │
 any machine ◄──── search · read · MCP (token) ──── relic5 serve
```

## The chain it sits on (already working)

| step | repo | output |
|---|---|---|
| scan | `Soul-Brews-Studio/relic4-scan` (public, branch alpha) | `~/.relic-scan/YYYY-MM.parquet`, `meta/sessions.parquet`; read `AGENTS.md` there |
| extract | `Soul-Brews-Studio/relic-extract` (private) | `~/.relic-extract/<stream>/YYYY-MM.parquet`, one row per chunk, `key` = blake2b-128 of the chunk text; settings in `~/.arra/relic.toml` |
| embed, search | `Soul-Brews-Studio/agent-relic-v4` (private) | `relic4 embed text-v2` reads `[extract].out/text`, vectors cached per key in `vec/_cache/<model>@<hash>`; `api.py` (bearer token, binds a tailnet address), `mcp_server.py`, `core.py`, `store.py` (LanceDB + ICU FTS), `remote_embed.py` (gb300) |

New since today: month rows carry `model`, `msg_id`, `out_tokens` (relic4-scan PR #34).

## What to bring from relic3 (`Soul-Brews-Studio/agent-relic-v3`, `hub/`)

- `hub/push.sh`: rsync over ssh, mtimes kept, never `--delete` on the hub, refuses a target that resolves elsewhere
  (white's `/Users/nat` is a symlink to `/home/nat`). In relic5 it pushes `~/.relic-extract` parts, not raw transcripts.
- `hub/add-machine.sh`: one label/tenant per machine, safe to re-run. In relic5: `parts/<machine>/`.
- `hub/systemd/relic3-serve.service`: token in a 0600 env file; serve refuses a non-loopback bind without it.
- `hub/launchd/studio.soulbrews.relic-push.plist` and the systemd timers: push after every extract.
- `hub/indexer.sh`: generations published with an atomic symlink switch, newest 3 kept.
- `hub/README.md`: the lessons (case-sensitive mirror on a Mac, the embed tunnel to m5's MLX).

Bring code with a note of where it came from (path + commit), not a vendored copy with no history.

## What relic5 adds

1. `relic5 push`: send this machine's new parts (by mtime/hash) to white.
2. `relic5 import`: old data, from relic3 week parquet (`~/.relic3-hub/index`, 79 G) and jsonl-truth (`~/jsonl-truth`).
3. `relic5 hub` (on white): merge every machine's parts; dedupe by `key`; queue keys with no vector; embed them (gb300
   first via remote_embed, then m5 MLX, then white CPU); publish a new generation.
4. `relic5 serve`: search, read a session, MCP; on white's tailnet address; one token per machine.

Embedding follows time (Nat: "time stamp is the truth because we can not make something more in the past"). A row's
`ts` never moves and the past only grows at the end, so each machine's stream has a watermark: every chunk at or before
it is embedded and never looked at again; a run embeds only chunks after it, then moves it. The key cache (one vector
per chunk text) still catches the rare old chunk that arrives late (an import, a mirror of another machine, a file whose
past changed per the relic-scan ledger): those are checked by key, not re-embedded by month.

Language: Python with uv, so relic4's LanceDB code comes over as is; the push client can stay a shell script.

## Measured today (2026-10-23, 20:50)

- white: Linux x86_64, 32 cores, 46 GB RAM, 250 GB free on `/`, no GPU. uv, bun and duckdb installed.
  `relic3-serve` there is inactive. Port 8787 on white is taken (a python3 process): pick another.
- m5: `~/.relic-extract` 799 MB (text 808 k chunks, thinking 102 k, tools 1.80 M); `~/relic4-fresh/vec` 20 GB.
- relic3 on m5: `~/.relic3` 19 G, stale since 10-15 (the MCP `relic_search` reads this one); `~/.relic3-hub` 79 G,
  indexed 20:41 today, 2.53 M events, vectors 530 k pending: its embed fails ("Unable to connect", the MLX engine).
- relic-scan does not scan `/Users/nat/.claude/projects` (8,266 files, a second account on m5); relic3 does.

## Rules (fleet-wide, do not break)

- Tailscale only: `*.follow-rankine.ts.net` or `100.x`. No NetBird, WireGuard, `black.local`.
- white has one login: `nat@white`.
- Long commands (index, embed, build, tests) run in a herdr pane (`/herdr-pane-run`), never a blocking or sleep-polled call.
- `rg` for search, never `grep -r` / `find` over `~` or `/opt/Code`.
- Never publish anything to claude.ai; no gist, no public paste. This repo is private.
- No `git push --force`; nothing deleted without a backup; never commit secrets or tokens.
- Transcripts are private work: nothing leaves the tailnet.
- Code goes through a branch + PR; files under 500 lines; every change has a test.

## First milestone

From m5: `relic5 push` sends `~/.relic-extract` to white; on white the hub holds it under `parts/m5/`; `relic5 serve`
on white answers a search from m5 over tailscale with a token. Measure each step (bytes, rows, seconds) and write it
in the README. Then mba (`nat@mba.follow-rankine.ts.net`), then import, then embed on gb300.

Questions or results: relic4-scan, pane `w11:p1` in herdr session `neo` (use fleet_send, address by pane id).
