# Where relic5 comes from (dug with relic5 itself, 2026-10-23)

Counts are sessions with a user message naming the tool (keyword, every machine, `role=user`, up to 300 hits each);
first seen .. last seen; then the sessions that mention it most. Reproduce: `/tmp/r5dig.py`-style loop over
`GET /api/search?q=<name>&role=user&horizon=archive`.

| tool | sessions | first .. last | where most of the work happened |
|---|---|---|---|
| session-search | 115 | 01-19 .. 10-23 | neo jsonl worktree 04d1d650 (09-16), digger 0697f729 (08-25), session-viewer b72e910c (09-01) |
| relic-scan (relic4-scan) | 105 | 01-29 .. 10-23 | relic4-scan 8b3b7c20 (10-22), agent-relic-v4 0f7f08a8 (10-22) |
| relic v1/v2 (agent-relic-v2) | 57 | 02-22 .. 10-23 | neo jsonl worktree 1719c605 (09-23 "call relic tail and get relic handoff cli"), 04d1d650, c51a219c |
| session-dream | 116 | 03-07 .. 10-23 | maw-js 26a2aa25 (05-17), jsonl-oracle f1e856a2 (09-10 "dig deep find all jsonl") |
| jsonl-truth | 84 | 03-25 .. 10-23 | maw-js 5b09130c (05-30), "embedding god" 6f5563d6 (10-21), digger c0af6afa (09-14) |
| jsonl-indexer | 35 | 05-04 .. 10-21 | idea session ee3babe1 (09-07), session-viewer b72e910c (09-01), neo jsonl 04d1d650 (09-16) |
| session-viewer | 49 | 05-15 .. 10-22 | digger c80b8013 (08-24), 0697f729 (08-25: Swift CLI as MCP, one verb table for CLI + MCP) |
| relic3 (agent-relic-v3) | 35 | 09-18 .. 10-23 | neo jsonl c51a219c (10-02), 1719c605 (09-23), agent-relic-v3 4ab7708a (10-03) |
| relic4 (agent-relic-v4) | 46 | 02-10 .. 10-23 | arra-oracle-v4 55199622 (09-26 "use relic cli"), c30e0ba2 (09-20) |
| relic-extract | 71 | 09-18 .. 10-23 | 1719c605, 04d1d650, relic-extract 008db2b3 (10-23) |
| jsonlmonth (Go) | 1 | 10-21 .. 10-22 | 6f5563d6: 39 GiB ingested in 14.6 s, FTS built afterwards |
| relic5 | 4 | 10-23 | this repo 50cb5858, relic4-scan 8b3b7c20, relic-extract 008db2b3, relic4 0f7f08a8 |

What each step left for relic5:
- session-search, session-dream, session-viewer: a session index behind an MCP. From session-viewer: one verb table
  generates both the CLI and the MCP tools.
- jsonl-truth, jsonl-indexer, jsonlmonth: one truth per line, keyed by hash, one file per month. Build the text
  index after the rows land, not row by row.
- relic v1/v2 → relic3: the hub on white, push over ssh, week partitions, BM25 + semantic, the five MCP tools, `relic tail`.
- relic4: LanceDB + ICU FTS, the key-addressed vector cache (1.03 M gemma vectors that seeded relic5), gb300 remote embed.
- relic-scan + relic-extract: scan every home, cut clean chunks with a stable key, one parquet per Bangkok month.
- relic5: one hub for every machine, months instead of weeks, the hub embeds nothing.

Note on session names: many top sessions are named by their first user message ("ok", "/model fable") because the
parts carry no host title yet (relic3's rule 1, `ai-title`). Asking relic-scan to carry the title would fix it.
