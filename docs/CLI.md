# CLI: `relic5` in Rust, the core in Python

Nat, 2026-10-26: "make relic5 cli using rust? … (just the cli) but the core same!". `relic5` on a machine is now a
Rust binary (`cli/`, about 2 MB). It owns the commands that talk to the hub, and it hands every other command, with
the same arguments, to the Python CLI under its second name, `relic5-core`. The hub, the index, the seals, the
embedder and the MCP server stay in Python, unchanged.

## Who does what

| command | where it runs | done by |
|---|---|---|
| `search`, `show`, `recap`, `conversation`, `readings`, `handoff`, `tail [-f] [--full]`, `pending`, `status`, `--version` | any machine, over the tailnet | **Rust** (`cli/src/cmds.rs`, line for line from `src/relic5/cli.py`) |
| `searched <words>`, `searched --link relic5://…`, `trace [<id>]` | any machine | **Rust** (`cli/src/searched.rs`): search what was already searched (past queries, found notes, tags), the way back from a message to the searches that found it, a trace chain. Hub: `/api/searched`, MCP `relic_searched` |
| `memory status \| list \| search` | any machine | **Rust** (`cli/src/notes.rs`): relic5's memory notes on the hub |
| `hindsight …` | m5 | **Rust** (`cli/src/memory.rs`, `top.rs`): the Hindsight bank, its dispatcher workers, the live TUI (docs/HINDSIGHT.md) |
| `import` (no subcommand) | each machine, by hand | **Rust** (`cli/src/import.rs`, docs/IMPORT.md); `bin/relic5-import` now calls it |
| `index`, `serve`, `seals`, `seal-day`, `gc`, `log`, `token`, `import repair-meta / relic3 / relic3-links / jsonl-truth` | the hub | Python core |
| `chain <session>`, `at <moment>`, `arc <words>` | any machine, over the tailnet | Python core (`src/relic5/timetravel.py`): time travel. `chain` = the sessions before and after one in the same worktree (relic3's `session --tree` / `chain`), `at` = everything around one hit or Bangkok time, `arc` = how a topic began and changed. Hub: `/api/chain`, `/api/at`, `/api/arc`; MCP `relic_chain`, `relic_at`, `relic_arc` (and `relic_recap`) |
| `skills [--since D] [--contains S] [--top N]`, `skills --sessions`, `skills --session <S>`, `skills --ai` | any machine, over the tailnet | Python core (`src/relic5/skills.py`, #299, #302): the skills a human typed (`/name`, Codex `$name`) in main-session prompts, once per session, relays and scheduled runs left out, checked against every indexed SKILL.md. Per skill: prompts, sessions, first/last, machines, launched (Skill tool calls), launched by an AI on its own, and months; per session; or one session's prompts. `--ai`: the skills an AI launched with no human `/name` typed before them in that session, by skill, model and project. Hub: `/api/skills`; MCP `relic_skills` |
| `duck-mem [8GB] [--no-save]`, `serve --duck-mem 8GB` | the hub, or Nat's tailnet | Python core (`src/relic5/hubmem.py`, #306): the hub's DuckDB memory cap (default 6GB). Read it, or set it on the running hub (DuckDB `SET memory_limit`, no restart), saved in `~/.config/relic5/hub.json` for the next start. A change needs a tokenless door (the hub itself or Nat's tailnet); `duck-mem SIZE` sends no token on purpose. Start order: `--duck-mem`, `RELIC5_DUCK_MEM`, hub.json, 6GB. Hub: `GET`/`POST /api/duck-mem`; MCP `relic_hub_memory` |
| `embed`, `mcp`, `tui`, `eval`, `--help`, no arguments, an unknown command | Mac clients / anywhere | Python core |

A command for the core replaces the Rust process (`exec`), so its output, exit code and signals are the core's own.
The core is found in this order: `$RELIC5_CORE`, `relic5-core` on `PATH`, beside the Rust binary,
`~/.local/share/uv/tools/relic5/bin/relic5-core`, `~/relic5/app/.venv/bin/relic5-core`. The Rust binary never runs
itself again.

## When you need `serve`, and when you don't (#311)

`relic5 serve` keeps the whole store warm: the DuckDB buffer (up to its `--duck-mem` cap), the open search tables, the
Map and Knowledge map, the page caches. Most of its memory goes to that warm state, mostly the Map (measured on a copy
of a full store: ~0.7 GB after searches, sessions and status, then ~8.9 GB once the Map was built). One machine's own
searches do not need any of it.

| you want | you need |
|---|---|
| the web pages, the Map, other machines searching this one, claude.ai's connector, saved searches, tags, found notes, artifacts | `relic5 serve` |
| semantic search (`semantic: true`: the vector matrices are the hub's warm memory) | `relic5 serve` (embedded answers by keyword and says so) |
| `search`, `show`, `recap`, `conversation`, `handoff`, `readings`, `tail`, `pending`, `status`, `searched`, `trace`, `chain`, `at`, `arc`, `skills` on this machine, and `relic5 mcp`'s read tools | nothing: a store on disk is enough |

How the client picks:

- `RELIC5_LOCAL=1` or `--local`: always embedded, reading the store at `--root` / `RELIC5_ROOT` / storage.json's root / `~/relic5`.
- Otherwise the hub (`RELIC5_URL`, or the default). If it cannot be reached (refused, no route, connect timeout, or
  no token file) **and** a store exists at the root, the same command is answered embedded. A hub that answers with
  an error is never re-asked locally.
- Neither: the hub's error, followed by the commands that fix it (`relic5 serve --root …`, `export RELIC5_LOCAL=1`,
  `export RELIC5_URL=…`).
- `relic5 status` starts with `"mode": {"used": "hub" | "local", "why": …, "url" | "root": …}`.

Embedded answers come from the same code as the hub's (`mcp.call_tool` and `src/relic5/routes.py`), so the output,
the error text and the exit codes match; tests/test_local.py compares them route by route, and test_rust_cli.py
compares the Rust and Python clients in embedded mode. Differences, on purpose:

- **Nothing is written.** No query log, no trace records, so results carry no `trace` and `relic_found`, `relic_tag`,
  `relic_saved add/remove`, `relic_artifact_put` and `relic_hub_memory set` answer "needs the hub". `you` is `local`.
- **Safe beside a writer.** DuckDB is an in-memory connection reading parquet (no database file, no lock); the index
  publishes a new Lance generation and renames `current.json` last, keeping 3 generations, so a reader holds one
  whole generation. `relic5 index`, `import` and the cycle write as before.
- **Opened per call, let go after.** The Rust client runs `relic5-core local-call <path> <params>` once per command.
  `relic5 mcp` opens the store on a call and closes it after `RELIC5_LOCAL_IDLE` seconds idle (default 60). Settings:
  `RELIC5_LOCAL_MEM` (DuckDB cap per reader, default 1GB), `RELIC5_LOCAL_THREADS` (4), `RELIC5_LOCAL_STICKY` (60:
  after the hub was unreachable, `relic5 mcp` answers embedded this long before trying it again).
- **Slow cold `status`.** `status` reads the readings, the git log and the query log in full. On a large store that
  takes tens of seconds in a fresh process (the hub keeps the answer cached).

## Same as before, on purpose

- **Settings:** `RELIC5_URL` (default white), `RELIC5_TOKEN_FILE` (default `~/.config/relic5/token`), and for
  `import` `~/.config/relic5/machine` or `RELIC5_MACHINE`.
- **Flags:** parsed the way `cli.py`'s `_opt` does (first occurrence, value after it; `--json` anywhere).
- **Requests:** the same routes and the same query strings, in the same order (`urlencode`, `+` for a space).
- **Output:** `--json` is `json.dumps(indent=1, ensure_ascii=False)` byte for byte (serde_json with `preserve_order`
  and `arbitrary_precision`, so numbers print as the hub wrote them). Text output slices, pads and splits by code
  point and by Python's whitespace rules (`cli/src/py.rs`).
- **Exit codes:** 0 ok · 1 error · 2 usage, or a 400/404 from the hub · 130 cancelled. A closed pipe
  (`relic5 search … | head`) ends quietly.
- **Version:** `relic5 --version` prints pyproject's version as CalVer, the same string as the Python CLI.

`tests/test_rust_cli.py` runs both CLIs against one test hub and compares stdout, stderr and exit code for each
command (19 cases; skipped when the binary is not built). Against the live hub on 2026-10-26 every command matched
except `recap`. That was the hub giving a different order on each call for tools and files with equal counts, also
between two Python calls; `recap.py` now breaks ties by name.

## Install

```sh
just cli         # a client: uv tool install (relic5-core), then the Rust binary at ~/.local/bin/relic5
just cli-bin     # the hub (white): the Rust binary only; its core is the hub venv's relic5-core
just cli-test    # cargo test, then the Rust-vs-Python comparison
```

`uv tool install` writes a Python `relic5` into `~/.local/bin` as well; `just cli` copies the Rust one over it and
keeps the replaced file as `relic5.bak-<version>`. After a plain `uv tool upgrade relic5` the Python one is back,
which still works (it is the full CLI); run `just cli` again. On white the hub's own venv (`~/relic5/app/.venv/bin/
relic5`, used by `relic5 index --wait` over ssh and inside Docker) is untouched; white builds its own Linux binary.
