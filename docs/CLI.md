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
| `embed`, `mcp`, `tui`, `eval`, `--help`, no arguments, an unknown command | Mac clients / anywhere | Python core |

A command for the core replaces the Rust process (`exec`), so its output, exit code and signals are the core's own.
The core is found in this order: `$RELIC5_CORE`, `relic5-core` on `PATH`, beside the Rust binary,
`~/.local/share/uv/tools/relic5/bin/relic5-core`, `~/relic5/app/.venv/bin/relic5-core`. The Rust binary never runs
itself again.

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
