"""tokens.py: the hub's tokens, one per name (a machine or a script), stored hashed.

  ~/.config/relic5/tokens.json (0600): {name: {"sha256": hex, "created": iso, "expires": iso|null,
                                        "old": {"sha256": hex, "until": iso}|absent}}

  relic5 token new <name> [--expires 90d]   prints the secret ONCE; only its sha256 is kept
  relic5 token list                          names, created, expires, rotation state (never a secret)
  relic5 token rotate <name> [--grace 24h]   a new secret; the old one keeps working until the grace ends
  relic5 token revoke <name>                 gone at once

The legacy file ~/.config/relic5/tokens (`<name> <secret>` lines, 2026-10-23) is still read, so nothing breaks;
`relic5 token new` refuses a name already there. Most readers need no token at all (doors.py: loopback, Nat's own
tailnet nodes); a token is for scripts and for nodes outside follow-rankine.
"""
import hashlib, hmac, json, os, re, secrets, time

from .types_ import Json
from . import store as rfs

PATH = os.environ.get("RELIC5_TOKENS_JSON", "~/.config/relic5/tokens.json")
LEGACY = os.environ.get("RELIC5_TOKENS", "~/.config/relic5/tokens")
NAME = re.compile(r"^[a-z0-9-]{1,40}$")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _later(spec: str | None) -> str:
    m = re.fullmatch(r"(\d+)([dh])", spec or "")
    if not m:
        raise SystemExit(f"bad duration {spec!r}: like 90d or 24h")
    secs = int(m.group(1)) * (86400 if m.group(2) == "d" else 3600)
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + secs))


def sha(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


class Tokens:
    def __init__(self, path: str = PATH, legacy: str = LEGACY) -> None:
        self.path, self.legacy = os.path.expanduser(path), os.path.expanduser(legacy)

    def load(self) -> dict[str, Json]:
        return rfs.read_json(self.path) if rfs.exists(self.path) else {}

    def _save(self, d: dict[str, Json]) -> None:
        os.makedirs(os.path.dirname(self.path), mode=0o700, exist_ok=True)
        tmp = self.path + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.write(fd, json.dumps(d, indent=1).encode())
        os.close(fd)
        os.replace(tmp, self.path)

    def legacy_tokens(self) -> dict[str, str]:
        if not rfs.exists(self.legacy):
            return {}
        return {p[0]: p[1] for p in (l.split() for l in open(self.legacy) if not l.startswith("#")) if len(p) == 2}

    def new(self, name: str, expires: str | None = None) -> str:
        if not NAME.match(name):
            raise SystemExit(f"bad name {name!r}: a-z 0-9 -")
        d = self.load()
        if name in d or name in self.legacy_tokens():
            raise SystemExit(f"{name} already has a token: rotate or revoke it")
        secret = secrets.token_urlsafe(32)
        d[name] = {"sha256": sha(secret), "created": _now(), "expires": _later(expires) if expires else None}
        self._save(d)
        return secret

    def rotate(self, name: str, grace: str = "24h") -> str:
        d = self.load()
        if name not in d:
            raise SystemExit(f"no token {name}")
        secret = secrets.token_urlsafe(32)
        d[name] = d[name] | {"sha256": sha(secret), "old": {"sha256": d[name]["sha256"], "until": _later(grace)}, "rotated": _now()}
        self._save(d)
        return secret

    def revoke(self, name: str) -> None:
        d = self.load()
        if name not in d:
            raise SystemExit(f"no token {name}" + (" (it is in the legacy file: remove its line there)" if name in self.legacy_tokens() else ""))
        del d[name]
        self._save(d)

    def list(self) -> list[Json]:
        out = [{"name": n, "created": v["created"], "expires": v.get("expires"), "rotating_until": (v.get("old") or {}).get("until"),
                "store": "hashed"} for n, v in sorted(self.load().items())]
        return out + [{"name": n, "store": "legacy (plain)"} for n in sorted(self.legacy_tokens())]

    def check(self, secret: str, now: str | None = None) -> str | None:
        """-> the name a secret belongs to, or None. Every entry is compared, so timing says nothing about which."""
        if not secret:
            return None
        now = now or _now()
        h, hit = sha(secret), None
        for n, v in self.load().items():
            live = not v.get("expires") or v["expires"] > now
            old = v.get("old") or {}
            if live and (hmac.compare_digest(h, v["sha256"]) or (old and old["until"] > now and hmac.compare_digest(h, old["sha256"]))):
                hit = hit or n
        for n, t in self.legacy_tokens().items():
            if hmac.compare_digest(secret.encode(), t.encode()):
                hit = hit or n
        return hit
