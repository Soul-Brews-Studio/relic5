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
| `src/relic5/gitlog.py` | git commits of every ghq repo as the `git` search layer (`relic_search with: "git"`): the record from 2025-03-25, the first Claude commit, back to before the oldest surviving transcript (2025-09-19). Our identities in the hub's `git-own` file; open-source clones keep only our commits | new |
| `deploy/systemd/relic5-serve.service` | the serve unit on white | agent-relic-v3 `hub/systemd/relic3-serve.service` |

Changed on purpose from the ports:
- Who needs no token (`doors.py`, Nat 2026-10-23): loopback, and Nat's own follow-rankine nodes. The second is
  checked with `tailscale whois` on the socket address (never X-Forwarded-For), and the Host must name the hub.
  A node shared in from another tailnet, or anything else, needs a token: one per machine, also used by scripts.
  `relic_status` says which door a request used (`you`). Honestly: **no password inside follow-rankine; anyone who
  joins that tailnet can read everything.** No proxy may sit in front of the hub, because it would make every
  client look local.
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

MCP is the easy way: an agent calls `relic_search`, `relic_show`, `relic_sessions`, `relic_session`, `relic_trace`,
`relic_saved`, `relic_asked`, `relic_tag`, `relic_tags`, `relic_found` and `relic_status` directly. Register it once per machine. `bin/relic5-mcp-headers` reads the 0600 token file, so the token
never sits in `~/.claude.json`:

```sh
claude mcp add-json -s user relic5 '{"type":"http","url":"http://white.follow-rankine.ts.net:8795/mcp",
  "headersHelper":"'"$PWD"'/bin/relic5-mcp-headers"}'
claude mcp get relic5        # Status: ✔ Connected (m5, 2026-10-23)
```

### Trace chains and saved searches

Every tool call is a record in the hub's query log (`logs/queries.jsonl`, 0600, never in git). A search's record keeps
its first 10 hits as links. Each `relic_search`, `relic_show`, `relic_session` and `relic_sessions` result carries
`trace: {id, root, parent}`. Pass `parent: <trace.id>` with the next call (opening a hit, or a narrower search) and
the hub links the two calls into one **chain**:

```text
search "rustfs backup"      #a1  ── relic_show hit 3   parent=#a1
                                 └─ search "rustfs backup white"  parent=#a1 ── relic_show hit 1
                                 └─ saved-search run (hourly): 12 hits, 2 new
```

- `relic_trace {"id": "<trace.id>"}` returns the whole chain, oldest first, each step with its depth, args and top hits.
  With no id it lists the newest chains.
- `relic_saved {"action": "add", "from": "<trace.id>", "every": 60}` keeps that search as a job. The hub re-runs it,
  puts each run in the chain of the search it came from, and writes a `saved-search` event to the Jobs log saying how
  many hits are new.
- `relic_found {"parent": "<trace.id>", "goal", "how", "found", "links"}` closes a chain: what the agent looked
  for, how it searched, and what it found ("nothing" counts). The hub adds the chain's own count of searches and
  opened hits. The MCP server's `initialize` answer carries instructions that ask every agent to pass `parent` and
  to call `relic_found` once at the end.
- `relic_asked {"since": "2026-10-24"}` tells what was looked into in a period (a Bangkok day, an ISO time, or `7d`):
  each distinct search and how often, the ones that found nothing, the found notes, the chains and the tags.
- `relic_tag {"target": "<relic5:// link | session id | trace.id>", "add": ["rustfs"], "note": "…"}` labels what was
  found, like digger's node tags; `relic_tags {"tag": "rustfs"}` lists what carries a tag. Append-only in
  `logs/tags.jsonl`. On the Search page, "Keep this hit" writes a found note and tags for the message being read.
- The Search page passes `parent` for you. The Asked page shows the charts, the full paged log, the chains and the saved
  searches. Over HTTP: `GET /api/trace`, `/api/access`, `/api/asked`, `/api/saved`, and `POST /api/saved`.

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

## Docs

- `docs/RETIRED.md`: the trinity rule (cease as active, keep as record, name what succeeded it) and the ledger of
  everything relic5 retired. Read it before you unload, remove or move anything.
- `docs/APPS.md`: every session-history app, with its verdict (keep, merge, retire).
- `docs/RESTORE.md`: the nightly backup and how to restore white.

## Next

1. mba (`nat@mba.follow-rankine.ts.net`): its own token, then `parts/mba/`.
2. Run push and index after every extract: a launchd/systemd timer, or relic-extract's offered `[extract] after` hook.
3. Import the old data: relic3 week parquet (`~/.relic3-hub/index`) and jsonl-truth.
4. Embed by watermark. Each machine and stream has a watermark (the newest `ts` embedded): a run embeds only rows after
   it, then moves it. The key cache (blake2b-128 of the chunk, seeded from m5's `~/relic4-scratch/vec/_cache`) catches
   the rare late-arriving old chunk. gb300 first, on demand only (its GPU is shared). After that, semantic `relic_search`.

## Pet Studio

`pet-studio/` makes things for the desk pet and puts them on it: a designer canvas any agent can draw on live
(Claude, Codex, omx), sprites, WebAssembly pet apps and firmware bundles. It runs on the Mac that holds the pets
(`just pet-studio`). Walkthrough with pictures: [pet-studio/docs/neo-pet.md](pet-studio/docs/neo-pet.md).

<img src="pet-studio/docs/images/neo-codex-idle.png" width="140"> <img src="pet-studio/docs/images/neo-idle.gif"> <img src="pet-studio/docs/images/neo-busy.gif"> <img src="pet-studio/docs/images/neo-heart.gif"> <img src="pet-studio/docs/images/neo-sleep.gif">

## License

GNU AGPL v3 or later (`LICENSE`), the same as Relic Scan (relic4-scan). If you run a changed hub as a service for others, share the changes.


## Storage: a disk or S3

The hub's data can live in a folder or in an S3 bucket, with the same code (`src/relic5/store.py`). Parts stay
parquet, the index stays LanceDB, DuckDB reads both from either place.

```sh
RELIC5_ROOT=s3://relic5-live/hub relic5 serve        # or: relic5 serve --root s3://relic5-live/hub
RELIC5_ROOT=s3://relic5-live/hub relic5 index
RELIC5_HUB=s3://relic5-live/hub bin/relic5-push       # a machine pushes into the bucket (aws CLI, push-only key)
```

- **Keys:** the hub reads `RELIC5_S3_KEY` (default `~/.config/relic5/s3-live`: line 1 the key, line 2 the secret),
  endpoint `RELIC5_S3_ENDPOINT` (default black's RustFS, `http://black.follow-rankine.ts.net:9200`). Machines push with
  a key that can put, list and get, never delete (`~/.config/relic5/s3-push`).
- **Logs on S3:** S3 has no append, so each log line is one small object under `<log>.d/`; the hub rolls them into a
  chunk every 10 minutes. Readers see the same lines either way.
- **Indexing on S3:** nothing sees a push land, so an S3 hub checks for changed parts every 2 minutes and runs
  `relic5 index` itself (`RELIC5_AUTO_INDEX=0` turns it off).
- **Mirror and switch** (Disk page, or `GET/POST /api/storage`): a mirror copies the data to the other kind of home on
  a clock, only what changed, never deleting there. Verify compares the data file by file (logs and the index are
  counted as behind, not failed). After a clean verify, "Switch at next start" moves the hub there when it restarts,
  and the old home becomes the mirror. The choice is kept in `storage.json` (`/config` in the container).
- **Tests:** `RELIC5_TEST_S3=s3://relic5-live/test uv run pytest tests/test_s3.py` runs a whole hub on the bucket.

## Whose .claude: homes

Every message carries the folder it was written in (relic-scan's `src_path`), so the hub can tell `nat`'s
`~/.claude` from `beta`'s, an extra home like `~/.claude1`, or a project's own `.claude`
(`…/exp/.claude-hello/.claude`). The home is the last `.claude*` / `.codex*` folder before `projects*`, `sessions`
or `backups` in that path.

- `relic_homes` / `GET /api/homes`: every home per machine, with relic-scan's `user@host`, sessions, messages, first
  and last.
- `home=` on `relic_search` and `relic_sessions` (and the Search page's "from" picker): a substring of the home,
  case-blind (`beta/.claude`, `.claude1`, `.claude-hello`). A message copied into several homes (a mirror, an
  export) is found from any of them; a hit shows its home and how many others hold it.
- The search index carries `home`, `homes` and `agent` from the first `relic5 index --force` after this change.
  Parts pushed before relic-scan wrote `src_path` (white's, today) show home unknown.
