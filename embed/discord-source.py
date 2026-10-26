"""discord-source.py: one Discord server's backup (maw atlas, on m5) as Hindsight items, JSON lines on stdout.

  python3 embed/discord-source.py <guild_id>        # items of that server
  python3 embed/discord-source.py --list            # every server: id, name, bank, run folder, messages

Source: ~/.maw/atlas-blobs/<Guild_Name>-<guildId>[-<UTC stamp>]/server.sqlite (neo-oracle#205); the newest folder per
server that has server.md (a finished run). One item = one conversation (a thread, or a channel's top level) in
~3,000-character blocks, oldest first: "[YYYY-MM-DD HH:MM] author: text (+ file names)". Bot messages are kept and
marked (bot). Document id discord:<guild>:<thread or channel>#<n>; tags discord, guild:<id>, channel:<name>.
Banks: one per server (Nat, 2026-10-26: "separate 1 per [server] to dig about the insight each server"), named from
~/.config/relic5/discord-banks.json (written on first use: discord-<slug of the name>, the id when the name has no
ASCII letters); edit it to rename or to send two servers to one bank.
"""
import glob, json, os, re, sqlite3, sys

ROOT = os.path.expanduser(os.environ.get("ATLAS_BLOBS", "~/.maw/atlas-blobs"))
MAP = os.path.expanduser("~/.config/relic5/discord-banks.json")
BLOCK = 3000


def runs() -> dict[str, tuple[str, str]]:
    """guild id -> (name, newest finished run folder)"""
    best: dict[str, tuple[str, str, float]] = {}
    for d in glob.glob(os.path.join(ROOT, "*/")):
        m = re.match(r"(.+)-(\d{15,})(?:-\d{8}T\d{6}Z)?$", os.path.basename(d.rstrip("/")))
        if not m or not os.path.exists(d + "server.md") or not os.path.exists(d + "server.sqlite"):
            continue
        name, gid = m.group(1), m.group(2)
        mt = os.path.getmtime(d + "server.sqlite")
        if gid not in best or mt > best[gid][2]:
            best[gid] = (name, d, mt)
    return {g: (n, d) for g, (n, d, _) in best.items()}


def slug(name: str, gid: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s)[:40].strip("-")
    return f"discord-{s}" if re.search(r"[a-z]", s) else f"discord-{gid}"


def banks(r: dict[str, tuple[str, str]]) -> dict[str, str]:
    m = json.load(open(MAP)) if os.path.exists(MAP) else {}
    changed = False
    for gid, (name, _) in r.items():
        if gid not in m:
            m[gid] = slug(name, gid)
            changed = True
    if changed:
        os.makedirs(os.path.dirname(MAP), exist_ok=True)
        json.dump(m, open(MAP, "w"), indent=1, ensure_ascii=False)
    return m


def items(gid: str) -> None:
    r = runs()
    if gid not in r:
        sys.exit(f"no finished run for guild {gid} under {ROOT}")
    name, d = r[gid]
    db = sqlite3.connect(d + "server.sqlite")
    chan = {str(i): (n or "", k or "") for i, n, k in db.execute("SELECT id, name, kind FROM channels")}
    rows = db.execute("""SELECT coalesce(thread_id, channel_id) AS conv, channel_id, thread_id, author_name, author_is_bot,
                                content, attachments_json, ts FROM discord_messages ORDER BY conv, ts""")
    conv, block, first, n = None, "", None, 0
    pretty = name.replace("_", " ")

    def flush(cid: str, ch_id: str, th_id: str | None) -> None:
        nonlocal block, first, n
        if block.strip():
            n += 1
            cname = chan.get(str(ch_id), ("?", ""))[0]
            where = f"#{cname}" + (f" › thread {chan.get(str(th_id), ('?', ''))[0]}" if th_id else "")
            sys.stdout.write(json.dumps({
                "document_id": f"discord:{gid}:{cid}#{n}", "content": block.strip(), "timestamp": first,
                "context": f"Discord server {pretty} · {where}",
                "tags": ["discord", f"guild:{gid}", f"channel:{cname}"]}, ensure_ascii=False) + "\n")
        block, first = "", None

    last = (None, None)
    for cid, ch_id, th_id, author, is_bot, content, att, ts in rows:
        cid = str(cid)
        if cid != conv:
            if conv is not None:
                flush(conv, *last)
            conv, n = cid, 0
        last = (ch_id, th_id)
        files = []
        try:
            files = [a.get("filename") or a.get("name") or "" for a in json.loads(att or "[]")]
        except ValueError:
            pass
        text = (content or "").strip() + (f" [files: {', '.join(f for f in files if f)}]" if any(files) else "")
        if not text:
            continue
        line = f"[{(ts or '')[:16].replace('T', ' ')}] {author or '?'}{' (bot)' if is_bot else ''}: {text}\n"
        if block and len(block) + len(line) > BLOCK:
            flush(conv, ch_id, th_id)
        first = first or ts
        block += line
    if conv is not None:
        flush(conv, *last)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--list":
        r = runs()
        b = banks(r)
        for gid, (name, d) in r.items():
            n = sqlite3.connect(d + "server.sqlite").execute("SELECT count(*) FROM discord_messages").fetchone()[0]
            print(json.dumps({"guild": gid, "name": name, "bank": b[gid], "folder": d, "messages": n}, ensure_ascii=False))
    elif len(sys.argv) > 1:
        banks(runs())
        items(sys.argv[1])
    else:
        sys.exit(__doc__)
