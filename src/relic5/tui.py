"""tui.py: `relic5 tui`, the hub in a terminal (Nat, 2026-10-23: "server then tui"). stdlib curses only; it reads the
same GET routes as the web UI, so it runs on any machine that reaches the hub (the tailnet door needs no token).

  1 status   machines, versions, freshness, store, warnings      4 jobs     the last event of each job
  2 live     the newest messages as they land                    5 queries  running, last, zero-hit
  3 search   / type, Enter search; ↑↓ pick, Enter show, Esc back
  r refresh · q quit · auto-refresh every 15 s
"""
import curses, json, textwrap, time, urllib.parse, urllib.request

TABS = ["status", "live", "search", "jobs", "queries"]


class Hub:
    def __init__(self, url, token=None):
        self.url, self.token = url.rstrip("/"), token

    def get(self, path, **q):
        req = urllib.request.Request(f"{self.url}{path}" + (("?" + urllib.parse.urlencode({k: v for k, v in q.items() if v not in (None, "")})) if q else ""))
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)


def size(b):
    return "?" if b is None else f"{b / 1e9:.2f} GB" if b > 1e9 else f"{b / 1e6:.1f} MB"


def ago(s):
    return "?" if s is None else f"{s} s" if s < 120 else f"{s // 60} min" if s < 7200 else f"{s // 3600} h"


def status_lines(s):
    out = [f"{s['code']['name']} {s['code']['version']} · {s['home']} · you: {s.get('you')}", ""]
    for w in s["warnings"] or ["no warnings"]:
        out.append(("! " if s["warnings"] else "  ") + w)
    out += ["", f"{'machine':<15} {'text':>9} {'tools':>10} {'newest row':<25} {'behind':>8} {'push age':>9}  relic-scan / extract / push"]
    f = s.get("freshness", {}).get("machines", {})
    for m in sorted(set(s["machines"]) | set(s.get("versions", {}))):
        x, v, fr = s["machines"].get(m, {}), s.get("versions", {}).get(m, {}), f.get(m, {})
        out.append(f"{m:<15} {(x.get('text') or {}).get('rows', 0):>9,} {(x.get('tools') or {}).get('rows', 0):>10,} "
                   f"{(x.get('text') or {}).get('newest_ts') or '?':<25} {ago(fr.get('lag_s')):>8} {ago(fr.get('push_age_s')):>9}  "
                   f"{v.get('relic-scan', '?')} / {v.get('relic-extract', '?')} / {v.get('relic5-push', '?')}")
    out += [""] + [f"{m:<15} {x['sync']}" for m, x in sorted(f.items()) if x.get("sync")]
    w = s["watermarks"]
    out += ["", f"BM25 index {w['fts']['at']} · vectors {w['vectors']['at']} pending {w['vectors']['pending']:,}",
            f"months {s['months']['total']} (sealed {s['months']['sealed']}, open {s['months']['open']})"]
    st, r = s.get("store", {}), s.get("resources", {})
    if st:
        out += ["", f"store {size(st.get('total'))} · search tables {size(st.get('search_total'))} · disk free {size(st['disk']['free'])} ({st['disk']['free_pct']}%)"
                + (f" · growth {size(st['growth']['per_day'])}/day" if st.get("growth", {}).get("per_day") else "")]
    if r:
        out.append(f"load {' / '.join(f'{x:.2f}' for x in r['load'])} on {r['cpus']} cpus · hub process {size((r.get('process') or {}).get('rss'))}"
                   + (f" · memory available {size(r['memory']['available'])}" if r.get("memory") else ""))
    return out


def live_lines(t):
    return [f"{(x['ts_th'] or '')[5:16].replace('T', ' ')}  {','.join(x['machines']):<12} {x['role']:<9} "
            f"{(x.get('session_name') or x['sid'] or '')[:26]:<26} {' '.join((x['text'] or '').split())}" for x in t["rows"]]


def job_lines(evs):
    return [f"{e['at'][5:19].replace('T', ' ')}  {e['verb']:<14} {e['state']:<8} rc={e.get('rc', '')!s:<3} {e.get('host', '')[:10]:<10} "
            f"{(str(e['done']) + ' ' + e.get('unit', '')) if e.get('done') is not None else '':<16} {e.get('message') or ''}" for e in evs]


def query_lines(q):
    out = [f"running now: {len(q['running'])}", ""]
    out += [f"  {r['at'][11:19]}  {r['door']:<16} {r['tool']:<15} {r['for_s']:>4} s  {r['query']}" for r in q["running"]]
    out += ["last:"] + [f"  {r['at'][5:19].replace('T', ' ')}  {r.get('door') or '':<16} {r.get('tool') or '':<15} {r.get('mode') or '':<8} "
                        f"{r.get('hits') if r.get('hits') is not None else '':>4} hits {r.get('ms', ''):>5} ms  {r.get('query') or ''}" for r in q["last"]]
    out += ["", "zero hits (what search misses):"] + [f"  {r['at'][5:19].replace('T', ' ')}  {r['query']}" for r in q["zero_hits"]]
    out += ["", "asked more than once:"] + [f"  {r['n']:>3}×  {r['query']}" for r in q["top"]]
    return out


def run(stdscr, hub):
    curses.curs_set(0)
    curses.use_default_colors()
    for i, c in enumerate((curses.COLOR_CYAN, curses.COLOR_YELLOW, curses.COLOR_RED, curses.COLOR_GREEN), 1):
        curses.init_pair(i, c, -1)
    stdscr.timeout(500)
    tab, lines, scroll, sel, last, err = 0, [], 0, 0, 0, None
    query, hits, shown, typing = "", [], None, False

    def load():
        nonlocal lines, err
        try:
            name = TABS[tab]
            if name == "status":
                lines = status_lines(hub.get("/api/status"))
            elif name == "live":
                lines = live_lines(hub.get("/api/tail", n=200))
            elif name == "jobs":
                lines = job_lines(hub.get("/api/log", n=300))
            elif name == "queries":
                lines = query_lines(hub.get("/api/queries"))
            err = None
        except Exception as ex:
            err = f"{type(ex).__name__}: {ex}"

    while True:
        if TABS[tab] != "search" and time.time() - last > 15:
            load()
            last = time.time()
        h, w = stdscr.getmaxyx()
        stdscr.erase()
        bar = "  ".join(f"{i + 1} {t}" for i, t in enumerate(TABS))
        stdscr.addnstr(0, 0, f" relic5 · {hub.url} ".ljust(w), w, curses.A_REVERSE)
        x = 0
        for i, t in enumerate(TABS):
            label = f" {i + 1} {t} "
            stdscr.addnstr(1, x, label, max(0, w - x), curses.color_pair(1) | (curses.A_BOLD | curses.A_UNDERLINE if i == tab else 0))
            x += len(label) + 1
        body = h - 4
        if TABS[tab] == "search":
            stdscr.addnstr(2, 0, f" / {query}" + ("▏" if typing else "") + ("   (Enter: search · ↑↓ pick · Enter: show · Esc: back)"), w - 1,
                           curses.color_pair(2) if typing else 0)
            if shown:
                view = shown
            else:
                view = []
                for i, x2 in enumerate(hits):
                    mark = "▶ " if i == sel else "  "
                    view.append(f"{mark}{x2['ts'][:16]} {','.join(x2['machines']):<10} {x2['role']:<9} {(x2.get('session_name') or '')[:24]:<24} "
                                f"{' '.join(x2['text_snippet'].split())}")
            rows = view[scroll:scroll + body - 1]
            for i, line in enumerate(rows):
                stdscr.addnstr(3 + i, 0, line, w - 1, curses.A_BOLD if (not shown and i + scroll == sel) else 0)
        else:
            for i, line in enumerate(lines[scroll:scroll + body]):
                attr = curses.color_pair(3) if line.startswith("! ") or " error " in line else 0
                stdscr.addnstr(2 + i, 0, line, w - 1, attr)
        foot = err or f"r refresh · q quit · ↑↓/PgUp/PgDn scroll · updated {time.strftime('%H:%M:%S', time.localtime(last))}"
        stdscr.addnstr(h - 1, 0, foot.ljust(w - 1), w - 1, curses.color_pair(3) if err else curses.A_DIM)
        stdscr.refresh()
        k = stdscr.getch()
        if k == -1:
            continue
        if typing:
            if k in (10, 13):
                typing = False
                try:
                    hits, sel, scroll, shown, err = hub.get("/api/search", q=query, limit=50)["hits"], 0, 0, None, None
                except Exception as ex:
                    err = f"{type(ex).__name__}: {ex}"
            elif k == 27:
                typing = False
            elif k in (curses.KEY_BACKSPACE, 127, 8):
                query = query[:-1]
            elif 32 <= k < 0x110000:
                query += chr(k)
            continue
        if k in (ord("q"), ord("Q")):
            return
        if ord("1") <= k <= ord(str(len(TABS))):
            tab, scroll, last, shown = k - ord("1"), 0, 0, None
        elif k == ord("r"):
            last = 0
        elif k == ord("/") and TABS[tab] == "search":
            typing, shown = True, None
        elif k == 27:
            shown, scroll = None, 0
        elif k in (10, 13) and TABS[tab] == "search" and hits and not shown:
            try:
                r = hub.get("/api/show", id=f"relic5://{hits[sel]['partition']}/{hits[sel]['uid']}", before=3, after=3)
                shown = []
                for note in r.get("notes", []):
                    shown.append(f"! {note}")
                for m in r["before"] + [r["target"]] + r["after"]:
                    head = f"── {(m.get('ts') or '')[:19]} {m.get('role')} {','.join(m.get('machines') or [])}" + ("  ◀ the hit" if m is r["target"] else "")
                    shown.append(head)
                    for para in (m.get("text") or "").splitlines() or [""]:
                        shown += textwrap.wrap(para, max(20, w - 2)) or [""]
                scroll = 0
            except Exception as ex:
                err = f"{type(ex).__name__}: {ex}"
        elif k == curses.KEY_DOWN:
            if TABS[tab] == "search" and not shown:
                sel = min(sel + 1, max(0, len(hits) - 1))
                scroll = max(scroll, sel - body + 3)
            else:
                scroll += 1
        elif k == curses.KEY_UP:
            if TABS[tab] == "search" and not shown:
                sel = max(sel - 1, 0)
                scroll = min(scroll, sel)
            else:
                scroll = max(0, scroll - 1)
        elif k == curses.KEY_NPAGE:
            scroll += body
        elif k == curses.KEY_PPAGE:
            scroll = max(0, scroll - body)


def main(url, token=None):
    curses.wrapper(run, Hub(url, token))
