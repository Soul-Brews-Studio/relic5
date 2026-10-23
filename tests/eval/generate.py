"""Known-item eval set from Nat's own history (relic4-scan's spec, 2026-10-23): n random user messages of 8+ words;
query = a 5-word fragment from the middle; truth = that message's session. Written to tests/eval/generated/ (gitignored:
it quotes transcripts). Usage: uv run python tests/eval/generate.py ~/.relic-extract/text 200"""
import json, random, re, sys

import duckdb

src, n = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 200
rows = duckdb.connect().execute(f"""SELECT sid, msgkey, text FROM read_parquet('{src}/*.parquet')
    WHERE role = 'user' AND chunk = 0 AND sid IS NOT NULL AND text NOT LIKE '/%' AND text NOT LIKE '[%'
      AND length(text) BETWEEN 60 AND 600 AND month >= '2025-12' USING SAMPLE reservoir({n * 40} ROWS) REPEATABLE (7)""").fetchall()
random.seed(7)
out, seen = [], set()
for sid, mk, text in rows:
    words = [w for w in re.split(r"\s+", text) if w]
    if len(words) < 8 or sid in seen:
        continue
    i = len(words) // 2 - 2
    frag = " ".join(words[i:i + 5])
    if not re.search(r"[A-Za-z฀-๿]{3}", frag):
        continue
    seen.add(sid)
    out.append({"q": frag, "want": [sid[:8]], "msgkey": mk})
    if len(out) == n:
        break
spec = {"about": "generated known-item set (5-word fragment of one user message; truth = its session)",
        "sessions": {o["want"][0]: next(s for s, _, _ in rows if s.startswith(o["want"][0])) for o in out}, "queries": out}
json.dump(spec, open("tests/eval/generated/known.json", "w"), ensure_ascii=False, indent=1)
print(f"{len(out)} queries -> tests/eval/generated/known.json")
