"""Build a paraphrase known-item set (issue #29): queries that say what a real message says, in other words.

  .venv/bin/python tests/eval/paraphrase.py [N=20] [--seed 29]
  -> tests/eval/generated/paraphrase.json (gitignored: query text stays off git), then
  uv run --extra embed python tests/eval/compare.py tests/eval/generated/paraphrase.json

Targets: N user messages from this machine's relic-extract text parts, seeded, one per session, spread over the
months, natural language only (12+ words, no code fences, no pasted blocks, no mid-turn wrappers or slash commands).
Queries: one headless `claude -p` call restates each target as a short search query that avoids its distinctive
words (no word of 5+ letters from the target, except very common ones), the way someone remembering the idea would
ask. A query passes when a top-10 hit is from the target's session (compare.py scores by session).
"""
import json, os, random, re, shutil, subprocess, sys

import duckdb

PARTS = os.path.expanduser(os.environ.get("RELIC_EXTRACT", "~/.relic-extract")) + "/text/2026-*.parquet"
OUT = os.path.join(os.path.dirname(__file__), "generated", "paraphrase.json")
# not a person writing: mid-turn wrappers, pastes, slash commands, and the briefs agents send each other
SKIP = re.compile(r"^(the user sent|<|\[|/|```|this session is being continued|you are |goal check-in|the user wants|in /|"
                  r"continue |original |[A-Z_]{4,}|review |task:|context:)", re.I)


def targets(n: int, seed: int) -> list[dict]:
    con = duckdb.connect()
    # a templated prompt (a cron job's, a worker brief) has no single right session: its opening must be in <= 2 sessions
    rows = con.execute(f"""WITH t AS (SELECT sid, month, text, regexp_replace(left(text, 80), '[0-9]', '', 'g') AS head FROM read_parquet('{PARTS}')
                             WHERE role = 'user' AND chunk = 0 AND length(text) BETWEEN 120 AND 700
                               AND len(string_split(text, ' ')) >= 12 AND text NOT LIKE '%```%' AND text NOT LIKE '%<pasted%'),
                           h AS (SELECT head FROM t GROUP BY head HAVING count(DISTINCT sid) <= 2)
                           SELECT sid, month, text FROM t SEMI JOIN h USING (head) ORDER BY sid, month, text""").fetchall()
    rng = random.Random(seed)
    rng.shuffle(rows)
    by_month: dict[str, list[tuple[str, str]]] = {}
    seen: set[str] = set()
    for sid, month, text in rows:
        if sid in seen or SKIP.match(text.strip()):
            continue
        seen.add(sid)
        by_month.setdefault(month, []).append((sid, text))
    out, months = [], sorted(by_month)
    while len(out) < n and any(by_month.values()):                      # round-robin over the months
        for m in months:
            if by_month[m] and len(out) < n:
                sid, text = by_month[m].pop()
                out.append({"alias": f"t{len(out) + 1:02d}-{m}", "sid": sid, "text": " ".join(text.split())})
    return out


PROMPT = """For each message below, write ONE search query someone would type months later to find it again, \
remembering the idea but not the wording. Rules: 6 to 14 words; same language as the message; do NOT reuse any word \
of 5 or more letters from the message (very common words like "about", "would", "should" are fine); no quotes.
Reply with JSON only: a list of {"alias": ..., "q": ...} in the same order.

"""


def paraphrase(ts: list[dict], agent: str) -> dict[str, str]:
    body = PROMPT + "\n".join(json.dumps({"alias": t["alias"], "message": t["text"]}, ensure_ascii=False) for t in ts)
    r = subprocess.run([shutil.which(agent) or agent, "-p", body, "--allowedTools", ""], capture_output=True, text=True, timeout=900)
    m = re.search(r"\[.*\]", r.stdout, re.S)
    if not m:
        raise SystemExit(f"{agent} -p gave no JSON list: {r.stdout[-400:]}{r.stderr[-400:]}")
    return {x["alias"]: x["q"] for x in json.loads(m.group(0))}


def main() -> None:
    a = sys.argv[1:]
    n = int(next((x for x in a if x.isdigit()), 20))
    seed = int(a[a.index("--seed") + 1]) if "--seed" in a else 29
    agent = a[a.index("--agent") + 1] if "--agent" in a else "claude"
    ts = targets(n, seed)
    qs = paraphrase(ts, agent)
    spec = {"about": f"Paraphrase known-item set (issue #29): {len(ts)} real user messages (seed {seed}), each restated by "
                     f"`{agent} -p` without its distinctive words. Ground truth = the message's session.",
            "sessions": {t["alias"]: t["sid"] for t in ts},
            "queries": [{"q": qs[t["alias"]], "want": [t["alias"]]} for t in ts if t["alias"] in qs]}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(spec, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"{len(spec['queries'])} queries -> {OUT}")


if __name__ == "__main__":
    main()
