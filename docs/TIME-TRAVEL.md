# Time travel and summaries

relic5 answers "what happened around this?" and "what was this about?" in one call each, so `/time-travel` and any
agent use the hub instead of stitching five searches together (Nat, 2026-11-05: "all should be relic5 subcommands, not
skill"). Issues #278–#282.

| ask | CLI | MCP | what comes back |
|---|---|---|---|
| the sessions before and after this one | `relic5 chain <session> [--before 3] [--after 3] [--scope auto\|worktree\|repo\|branch] [--gap-hours 6]` | `relic_chain` | oldest first: when (Bangkok), machine, first ask, last reply, files edited, the session reading; gaps and parallel runs marked |
| everything around one moment | `relic5 at <relic5://… \| uid \| 'YYYY-MM-DD HH:MM'> [--span 30m]` | `relic_at` | the readings whose windows hold it, every session running then with what it last said, commits, hub searches and found notes, the hit's neighbours |
| how a topic began and changed | `relic5 arc <words> [--since] [--until]` | `relic_arc` | hits per month (sessions, projects, machines), first and last hit, turning points, day and session readings, earlier found notes |
| one session, short | `relic5 recap <session>` | `relic_recap` | the human's turns, tools, files edited, how it ended, plus the session reading |
| what a model made of a session | `relic5 readings --kind sessions [--q words]` | `relic_readings {kind: sessions}` | type, focus, work, ended, open, repos, en, th |

## Session readings

relic-extract's `report/session_readings.py` reads each main session once (again when it grows by 25%) with the same
lanes as the window readings (z.ai, gb300, fm) and appends to `~/.relic-extract/report/session-readings.jsonl`.
`bin/relic5-push` (push format 10) copies it to the hub's `readings/sessions/<machine>.jsonl`, and the window readings
to `readings/<machine>.jsonl`; both were copied by hand before, and the hub's copy fell ten days behind.

A session reading gives `relic_session` a `display_title` when the session's own title says nothing ("hello", "ok",
"/model opus", a mid-turn wrapper).

## Freshness

`relic5 status` has a `readings` block (newest window per machine, model and grain; the newest day; closed months after
the last sealed recap that have none) and warns when the newest day reading is more than two days old or a month recap
is missing. `relic5 pending` prints one line for it.
