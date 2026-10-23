"""doors.py: who may read the hub without a token. Nat, 2026-10-23: "if localhost or vpn follow-rankine please bypass
the password, i never let others join follow-rankine".

A request comes in through one door, checked in this order, using the socket's addresses only (never X-Forwarded-For;
uvicorn runs with proxy_headers=False):
  loopback          server and client are 127.0.0.1 / ::1 and the Host names this box (localhost, 127.0.0.1, [::1])
  tailnet:<node>    the client is a tailscale address (100.64.0.0/10) and `tailscale whois` says its owner is the
                    hub's own owner (nat.wrw@gmail.com on follow-rankine). A node shared in from another tailnet (the
                    clinic's yd-linux, windeachawat9938@) has another owner and still needs a token.
  token:<machine>   a Bearer token (or the UI cookie), one per machine, for anything else and for scripts
Both tokenless doors also need a Host header that names the hub (its tailnet name, short name, tailnet IP or
loopback), so a web page in a browser cannot reach the hub by DNS rebinding (relic4's Host check, api.py PR #5).
Honest limit: no password inside follow-rankine; anyone who joins that tailnet as Nat can read everything.
"""
import ipaddress, json, socket, subprocess, time

LOOPBACK = {"127.0.0.1", "::1"}
CGNAT = ipaddress.ip_network("100.64.0.0/10")
TTL = 300


def tailscale_whois(ip):
    """-> {"node": name, "login": owner} or None."""
    try:
        out = subprocess.run(["tailscale", "whois", "--json", ip], capture_output=True, text=True, timeout=3)
        d = json.loads(out.stdout)
        return {"node": d["Node"]["Name"].rstrip("."), "login": d["UserProfile"]["LoginName"]}
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return None


def tailscale_self():
    """-> (owner login, {names and addresses that mean this hub})."""
    try:
        d = json.loads(subprocess.run(["tailscale", "status", "--json"], capture_output=True, text=True, timeout=3).stdout)
        s = d["Self"]
        name = s["DNSName"].rstrip(".")
        return d["User"][str(s["UserID"])]["LoginName"], {name, name.split(".")[0], *s.get("TailscaleIPs", [])}
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired):
        return None, set()


class Doors:
    def __init__(self, tokens, owner=None, names=None, whois=tailscale_whois, enabled=True):
        self.tokens, self.whois, self.enabled = tokens, whois, enabled
        if enabled and (owner is None or names is None):
            o, n = tailscale_self()
            owner, names = owner or o, names if names is not None else n
        self.owner = owner
        self.names = {x.lower() for x in (names or set())} | {socket.gethostname().lower(), "localhost", "127.0.0.1", "::1"}
        self.cache = {}

    def _whois(self, ip):
        hit = self.cache.get(ip)
        if hit and time.time() - hit[0] < TTL:
            return hit[1]
        r = self.whois(ip)
        self.cache[ip] = (time.time(), r)
        return r

    def door(self, server, client, host, bearer):
        """-> "loopback" | "tailnet:<node>" | "token:<machine>" | None (refused)."""
        if bearer:
            import hmac
            ok = [m for m, t in self.tokens.items() if hmac.compare_digest(bearer.encode(), t.encode())]
            return f"token:{ok[0]}" if ok else None
        if not self.enabled:
            return None
        host = (host or "").lower().strip("[]")
        if host not in self.names:
            return None
        if server in LOOPBACK and client in LOOPBACK and host in {"localhost", "127.0.0.1", "::1"}:
            return "loopback"
        try:
            ip = ipaddress.ip_address(client)
        except ValueError:
            return None
        if ip.version == 4 and ip in CGNAT and self.owner:
            w = self._whois(client)
            if w and w["login"] == self.owner:
                return f"tailnet:{w['node'].split('.')[0]}"
        return None
