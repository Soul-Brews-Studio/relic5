"""hindsight-source.py: runs on the hub (white), reads one relic5 source from ~/relic5/parts and prints Hindsight items
as JSON lines, newest first: {"document_id", "content", "timestamp", "context", "tags"}. embed/hindsight-import.py on m5
runs it over ssh and queues the items (Nat, 2026-10-26: "memory first then vault, git, thinking, then sessions").

  ~/relic5/app/.venv/bin/python - <source> [--parts ~/relic5/parts] < hindsight-source.py

  memory    every memory note (.md) under parts/<machine>/memory/, one item per file (MEMORY.md indexes skipped)
  vault     ψ vault notes (parts/*/vault/notes.parquet), one item per note, chunks joined in order
  git       our own commits (author nat/beta/oracles and Claude/Codex co-authored), per repo per day
  thinking  thinking blocks per session, in about 3,000-character blocks
  sessions  every session's user and assistant turns, de-duplicated across machines (msgkey, chunk), in ~3,000-character
            blocks, id "<session>#<n>" as `relic5 memory import <session>` writes them; newest sessions first
"""
import json, os, re, sys, time
from datetime import datetime, timezone

PARTS = os.path.expanduser(sys.argv[sys.argv.index("--parts") + 1] if "--parts" in sys.argv else "~/relic5/parts")
BLOCK = 3000


def out(doc: str, content: str, ts: str | None, context: str, tags: list[str]) -> None:
    content = content.strip()
    if content:
        sys.stdout.write(json.dumps({"document_id": doc, "content": content, "timestamp": ts, "context": context, "tags": tags},
                                    ensure_ascii=False) + "\n")


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def memory() -> None:
    files = []
    for m in sorted(os.listdir(PARTS)):
        root = os.path.join(PARTS, m, "memory")
        for d, _, fs in os.walk(root):
            for f in fs:
                if f.endswith(".md") and f != "MEMORY.md":
                    p = os.path.join(d, f)
                    files.append((os.path.getmtime(p), m, p))
    for mt, m, p in sorted(files, reverse=True):
        rel = os.path.relpath(p, os.path.join(PARTS, m, "memory"))
        project = rel.split("/")[1] if rel.count("/") >= 2 else rel.split("/")[0]
        text = open(p, encoding="utf-8", errors="replace").read()
        kind = re.search(r"^\s*type:\s*(\w+)", text, re.M)
        out(f"memory:{m}/{rel}", text, iso(mt), f"memory note {os.path.basename(p)} · {project} · machine {m}",
            ["relic5", "source:memory", f"machine:{m}"] + ([f"kind:{kind.group(1)}"] if kind else []))


def duck():
    import duckdb
    return duckdb.connect()


def vault() -> None:
    con = duck()
    q = f"""SELECT vault, path, any_value(title) AS title, max(ts) AS ts, string_agg(text, '' ORDER BY chunk) AS text
            FROM read_parquet('{PARTS}/*/vault/notes.parquet', union_by_name = true)
            WHERE text IS NOT NULL GROUP BY vault, path ORDER BY max(ts) DESC NULLS LAST"""
    cur = con.execute(q)
    while rows := cur.fetchmany(2000):
        for vault_, path, title, ts, text in rows:
            out(f"vault:{vault_}:{path}", text, ts, f"ψ vault note {title or os.path.basename(path or '')} · {path} · vault {vault_}",
                ["relic5", "source:vault"])


OURS = re.compile(r"(nat|beta|oracle|weerawan|laris|soul-brews|nazt|claude|codex|noreply@anthropic)", re.I)


def git() -> None:
    days: dict[tuple[str, str], list[str]] = {}
    for m in sorted(os.listdir(PARTS)):
        root = os.path.join(PARTS, m, "git")
        for d, _, fs in os.walk(root):
            for f in fs:
                if not f.endswith(".log") or "/_" in d or f.startswith("_"):
                    continue
                repo = os.path.relpath(os.path.join(d, f[:-4]), root)
                for line in open(os.path.join(d, f), encoding="utf-8", errors="replace"):
                    p = line.rstrip("\n").split("\x1f")
                    if len(p) < 6:
                        continue
                    sha, adate, _, name, email, subject = p[:6]
                    body = " ".join(p[6:]).strip()
                    if not OURS.search(name + " " + email + " " + body):
                        continue
                    days.setdefault((repo, adate[:10]), []).append(f"{adate[11:16]} {sha[:8]} {name}: {subject}" + (f" — {body[:300]}" if body else ""))
    for (repo, day), lines in sorted(days.items(), key=lambda kv: kv[0][1], reverse=True):
        lines = sorted(set(lines))
        for i in range(0, len(lines), 40):
            out(f"git:{repo}:{day}#{i // 40 + 1}", f"Commits in {repo} on {day}:\n" + "\n".join(lines[i:i + 40]),
                f"{day}T12:00:00+07:00", f"git history of {repo}", ["relic5", "source:git"])


def thinking() -> None:
    con = duck()
    cur = con.execute(f"""SELECT sid, list(text ORDER BY ts, chunk) AS t, min(ts) AS first, max(ts) AS last
                          FROM read_parquet('{PARTS}/*/thinking/*.parquet', union_by_name = true)
                          WHERE sid IS NOT NULL AND text IS NOT NULL GROUP BY sid ORDER BY max(ts) DESC""")
    while rows := cur.fetchmany(500):
        for sid, texts, first, _ in rows:
            block, n = "", 0
            for t in dict.fromkeys(texts):   # copies from two machines once
                if block and len(block) + len(t) > BLOCK:
                    n += 1
                    out(f"thinking:{sid}#{n}", block, first, f"the assistant's thinking in session {sid}", ["relic5", "source:thinking"])
                    block = ""
                block += t.strip() + "\n\n"
            if block:
                n += 1
                out(f"thinking:{sid}#{n}", block, first, f"the assistant's thinking in session {sid}", ["relic5", "source:thinking"])


def sessions() -> None:
    con = duck()
    con.execute(f"""CREATE TEMP TABLE t AS
                    SELECT DISTINCT ON (msgkey, chunk) sid, ts, role, text FROM read_parquet('{PARTS}/*/text/*.parquet', union_by_name = true)
                    WHERE sid IS NOT NULL AND text IS NOT NULL AND role IN ('user', 'assistant')""")
    cur = con.execute("""SELECT t.sid, t.ts, t.role, t.text FROM t
                         JOIN (SELECT sid, max(ts) AS last FROM t GROUP BY sid) s USING (sid)
                         ORDER BY s.last DESC, t.sid, t.ts""")
    sid, block, first, n = None, "", None, 0

    def flush() -> None:
        nonlocal block, first, n
        if block:
            n += 1
            out(f"{sid}#{n}", block, first, f"relic5 session {sid}", ["relic5", "source:session"])
        block, first = "", None

    while rows := cur.fetchmany(5000):
        for s_, ts, role, text in rows:
            if s_ != sid:
                flush()
                sid, n = s_, 0
            line = f"[{(ts or '')[:16]}] {role}: {text.strip()}\n\n"
            if block and len(block) + len(line) > BLOCK:
                flush()
            first = first or ts
            block += line
    flush()


if __name__ == "__main__":
    src = sys.argv[1] if len(sys.argv) > 1 else ""
    fn = {"memory": memory, "vault": vault, "git": git, "thinking": thinking, "sessions": sessions}.get(src)
    if not fn:
        sys.exit("hindsight-source.py memory|vault|git|thinking|sessions [--parts DIR]")
    t0 = time.time()
    fn()
    print(f"# {src} done in {time.time() - t0:.0f}s", file=sys.stderr)
