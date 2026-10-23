# relic5

One hub on white for every machine's extracted history: push, month store, MCP. Embedding comes next. See
[BRIEF.md](BRIEF.md) for the why.

```
 m5 / mba / …                                         white (white.follow-rankine.ts.net, tailscale)
 relic-scan ─► relic-extract ─► bin/relic5-push ─ssh─►  ~/relic5/parts/<machine>/{text,thinking,tools,vault,meta}
                                                        relic5 index ─► ~/relic5/index/YYYY-MM/manifest.json
 any machine ◄──── MCP POST /mcp · GET /api/* (token) ── relic5 serve 100.103.52.67:8795
```

## Pieces

| file | what | came from |
|---|---|---|
| `bin/relic5-push` | rsync `~/.relic-extract/{text,thinking,tools,vault}` and relic-scan's `meta/sessions.parquet` to `parts/<machine>/` | agent-relic-v3 `hub/push.sh` @6a6d9d8 |
| `src/relic5/parts.py` | one partition per Bangkok month (relic3's week made a month), per-month manifest, sealed vs open | agent-relic-v3 `hub/indexer.sh` idea |
| `src/relic5/query.py` | search / show / sessions / session over the parts, folded by `msgkey` across machines | result shapes from agent-relic-v3 `src/search/query.ts` @9f0bdb5 |
| `src/relic5/mcp.py` | the five tools with v3 names and input schemas, JSON-RPC | agent-relic-v3 `src/mcp/tools.ts`, `server.ts` @9f0bdb5 |
| `src/relic5/api.py` | `POST /mcp`, `GET /api/*`, `/health`; a bearer token on every request | agent-relic-v4 `api.py`, PR #5 @febfdb7 and PR #6 @b399119 |
| `deploy/systemd/relic5-serve.service` | the serve unit on white | agent-relic-v3 `hub/systemd/relic3-serve.service` |

Changed on purpose from the ports:
- No loopback exemption: the token is required from 127.0.0.1 too. A hub serves many machines, and a proxy on the
  box would make every client look local (relic4's advice).
- Ids are the `msgkey`, the same on every machine, with `:<chunk>` for later chunks. Links are
  `relic5://<YYYY-MM>/<msgkey>`.
- The same message pushed by two machines is one hit. Its `machines` field lists every machine that sent it, and the
  first by name supplies the row.
- `relic_show` answers a `relic3://` id or a v3 uid with "a relic3 id: search relic5 again", never with "not found".

## Use

On the hub (white):

```sh
git clone -b main https://github.com/Soul-Brews-Studio/relic5 ~/relic5/app && cd ~/relic5/app && uv sync --no-dev
.venv/bin/relic5 token add m5            # prints the token once; ~/.config/relic5/tokens is 0600
cp deploy/systemd/relic5-serve.service ~/.config/systemd/user/ && systemctl --user enable --now relic5-serve
```

On a machine that pushes and reads:

```sh
(umask 077; ssh nat@white.follow-rankine.ts.net '~/relic5/app/.venv/bin/relic5 token add mba' > ~/.config/relic5/token)
bin/relic5-push                          # waits out relic-extract's lock (exit 75 while it runs)
ssh nat@white.follow-rankine.ts.net '~/relic5/app/.venv/bin/relic5 index'
uv run relic5 search ภาษาไทย --limit 5   # RELIC5_URL defaults to http://white.follow-rankine.ts.net:8795
```

An MCP client points at `http://white.follow-rankine.ts.net:8795/mcp` with `Authorization: Bearer <token>`. The
tools are `relic_search`, `relic_show`, `relic_sessions`, `relic_session` and `relic_status`.

Tests: `uv run pytest` (33 tests: push against a fake hub, month manifests, fold, Thai, cursor, MCP, token).

## Measured (milestone 1, m5 to white, 2026-10-23 21:05–21:10 +07)

| step | result |
|---|---|
| push, first run | 10.1 s, rc 0; sent text 186.6 MB, thinking 18.0 MB, tools 304.7 MB, vault 318.8 MB, meta 2.9 MB |
| verify (m5 vs white) | text 15 files 810,444 rows 725,165 keys · thinking 15 / 101,945 / 99,975 · tools 15 / 1,811,069 / 1,621,838 · vault 1 / 252,555: all equal |
| `relic5 index` | 0.9 s, 15 month manifests (2025-09 … 2026-10 sealed, 2026-10 open, undated empty) |
| `/health` without a token or with a bad one | 401 |
| search "ภาษาไทย", limit 20, from m5 | 200, 1.02 s |
| search "watermark embed" | 200, 0.90 s |
| search "relic5" with tools | 200, 1.11 s |
| MCP `tools/call relic_search` | 0.89 s |
| `relic_show` of a link, before/after 1 | 0.18 s |
| `relic_sessions` | 0.08 s, 11,613 main sessions |
| `relic_status` | 0.01 s |

Search is keyword: every word must occur, with ILIKE over the parquet in place. There is no cache, so expect about 1 s a query.

## Next

1. mba (`nat@mba.follow-rankine.ts.net`): its own token, then `parts/mba/`.
2. Run push and index after every extract: a launchd/systemd timer, or relic-extract's offered `[extract] after` hook.
3. Import the old data: relic3 week parquet (`~/.relic3-hub/index`) and jsonl-truth.
4. Embed by watermark. Each machine and stream has a watermark (the newest `ts` embedded): a run embeds only rows after
   it, then moves it. The key cache (blake2b-128 of the chunk, seeded from m5's `~/relic4-scratch/vec/_cache`) catches
   the rare late-arriving old chunk. gb300 first, on demand only (its GPU is shared). After that, semantic `relic_search`.
