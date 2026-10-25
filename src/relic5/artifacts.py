"""artifacts.py: what agents make for an oracle, kept on the hub and shown on its page (Nat, 2026-10-24: "provide mcp
to let omx / claude code draw images and put here in oracle page / video / images / 3d web like nft artifact").

An agent draws or renders something (a portrait, a short video, a 3D scene, a small web piece) and hands it to the hub
with the MCP tool relic_artifact_put or POST /api/artifact. The hub keeps the bytes as they came, content-addressed,
and one line of metadata per artifact:

  <root>/artifacts/files/<id>.<ext>      the file; id = the first 16 hex of its sha256, so the same bytes are one file
  <root>/artifacts/index.jsonl           {id, oracle, title, kind, ext, mime, bytes, sha256, at, by, note, prompt, session}

Kinds by extension: image (png jpg webp gif svg), video (mp4 webm mov), model (glb, gltf), web (html). Nothing is
converted, fetched or run on the hub. The page shows a web piece or an SVG in a sandboxed frame, served with a CSP
sandbox header and nosniff, so its scripts never run with the hub's origin. Like an NFT's record and unlike one,
nothing is minted: the record is this hub's own line, with who sent it, when, and the prompt that made it.
"""
import base64, hashlib, json, os, re, threading, time

from .query import NotFound, UsageError
from .types_ import Json
from . import store as rfs

KINDS = {"png": ("image", "image/png"), "jpg": ("image", "image/jpeg"), "jpeg": ("image", "image/jpeg"),
         "webp": ("image", "image/webp"), "gif": ("image", "image/gif"), "svg": ("image", "image/svg+xml"),
         "mp4": ("video", "video/mp4"), "webm": ("video", "video/webm"), "mov": ("video", "video/quicktime"),
         "glb": ("model", "model/gltf-binary"), "gltf": ("model", "model/gltf+json"), "html": ("web", "text/html; charset=utf-8")}
MAX_BYTES = 60 * 1024 * 1024
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")
_LOCK = threading.Lock()


def _dir(root: str) -> str:
    return os.path.join(root, "artifacts")


def put(root: str, oracle: str, title: str, ext: str, data: bytes, note: str | None = None, prompt: str | None = None,
        session: str | None = None, by: str | None = None) -> Json:
    """Keep one artifact; the same bytes for the same oracle again answer the first record (dedup: True)."""
    oracle, ext = (oracle or "").strip(), (ext or "").lower().lstrip(".")
    if not NAME.match(oracle):
        raise UsageError("oracle must be the oracle's name, like neo-oracle (letters, digits, . _ -)")
    if ext not in KINDS:
        raise UsageError(f"unsupported file type .{ext} (allowed: {', '.join(sorted(KINDS))})")
    if not data:
        raise UsageError("the file is empty")
    if len(data) > MAX_BYTES:
        raise UsageError(f"the file is {len(data)} bytes; the hub keeps artifacts up to {MAX_BYTES} bytes")
    sha = hashlib.sha256(data).hexdigest()
    aid = sha[:16]
    with _LOCK:
        for r in listing(root, oracle)["artifacts"]:
            if r["sha256"] == sha:
                found: Json = r | {"dedup": True}
                return found
        path = os.path.join(_dir(root), "files", f"{aid}.{ext}")
        if not rfs.exists(path):
            rfs.write_bytes(path, data)
        kind, mime = KINDS[ext]
        rec: Json = {"id": aid, "oracle": oracle, "title": (title or "").strip()[:200] or f"{kind} for {oracle}", "kind": kind,
                     "ext": ext, "mime": mime, "bytes": len(data), "sha256": sha, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                     "by": by, "note": (note or "")[:2000] or None, "prompt": (prompt or "")[:8000] or None, "session": session}
        rfs.append_line(os.path.join(_dir(root), "index.jsonl"), json.dumps(rec, ensure_ascii=False), 0o644)
    return rec | {"url": f"/api/artifact/{aid}", "page": f"/#tab=oracles&oracle={oracle}"}


def put_b64(root: str, a: Json, by: str | None) -> Json:
    """The MCP form: data (base64) or text (an HTML or SVG piece as text), plus filename or ext."""
    ext = str(a.get("ext") or os.path.splitext(str(a.get("filename") or ""))[1] or "")
    if a.get("text") is not None:
        data = str(a["text"]).encode("utf-8")
    elif a.get("data") is not None:
        try:
            data = base64.b64decode(str(a["data"]).split(",", 1)[-1], validate=False)   # a data: URL works too
        except ValueError:
            raise UsageError("data must be base64")
    else:
        raise UsageError("give data (base64 of the file) or text (an HTML or SVG piece)")
    return put(root, str(a.get("oracle") or ""), str(a.get("title") or ""), ext, data, a.get("note"), a.get("prompt"), a.get("session"), by)


def listing(root: str, oracle: str | None = None, limit: int = 500) -> Json:
    """Newest first; one oracle's, or every oracle's with a count per oracle."""
    p = os.path.join(_dir(root), "index.jsonl")
    rows: list[Json] = []
    if True:
        for line in rfs.read_lines(p):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not oracle or r.get("oracle") == oracle:
                rows.append(r | {"url": f"/api/artifact/{r['id']}"})
    rows.reverse()
    per: dict[str, int] = {}
    for r in rows:
        per[r["oracle"]] = per.get(r["oracle"], 0) + 1
    return {"artifacts": rows[:limit], "total": len(rows), "oracles": per}


def file_of(root: str, aid: str) -> tuple[str, str, str]:
    """-> (path, mime, kind) of one artifact."""
    if not re.fullmatch(r"[0-9a-f]{16}", aid or ""):
        raise NotFound("no such artifact")
    for r in listing(root)["artifacts"]:
        if r["id"] == aid:
            path = os.path.join(_dir(root), "files", f"{aid}.{r['ext']}")
            if rfs.isfile(path):
                return path, r["mime"], r["kind"]
    raise NotFound("no such artifact")
