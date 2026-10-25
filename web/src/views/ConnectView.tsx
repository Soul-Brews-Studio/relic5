import { useEffect, useState } from "react";
import { usePoll } from "../api";
import { DataTable } from "../components/DataTable";
import { ago, bkk, num } from "../format";
import { Btn, Chip, cx, inputCls, PageHead, SectionHead, State } from "../components/ui";

interface Device { door: string; client: string; first: string; last: string; calls: number; calls_24h: number;
                   tools: Record<string, number>; p50_ms: number | null }

/** How to connect an agent to this hub over MCP: native commands only, ready to copy (Nat, 2026-08-22, arra-memory:
 *  "use the native commands directly", not a wrapper), with this page's own address filled in, and a live test. */

interface Tool { name: string; description?: string }

function Cmd({ title, why, cmd }: { title: string; why: string; cmd: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="rounded-2xl border border-line bg-panel px-6 py-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="m-0 text-base font-bold text-text">{title}</h3>
        <Btn type="button" onClick={() => { navigator.clipboard.writeText(cmd); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
          {copied ? "Copied" : "Copy"}
        </Btn>
      </div>
      <p className="m-0 mt-1 max-w-[75ch] text-sm text-muted">{why}</p>
      <pre className="m-0 mt-4 overflow-x-auto rounded-xl bg-deep px-4 py-3.5 font-mono text-xs leading-relaxed whitespace-pre-wrap text-soft select-all">{cmd}</pre>
    </div>
  );
}

export interface LastUsed { last_used?: string; last_ip?: string | null; last_via?: "tunnel" | "direct" | null; last_path?: string | null }
interface TokenRow extends LastUsed { name: string; created?: string; expires?: string | null; rotating_until?: string | null; store: string }

/** When a token or connector was last used, and from where: "4 min ago" over "via the tunnel · 203.0.113.9". */
export function LastUsedCell({ r }: { r: LastUsed }) {
  if (!r.last_used) return <span className="text-faint">never</span>;
  const where = [r.last_via === "tunnel" ? "via the tunnel" : null, r.last_ip, r.last_path].filter(Boolean).join(" · ");
  return (
    <span className="flex flex-col">
      <span title={bkk(r.last_used)}>{ago(r.last_used)}</span>
      {where && <span className="font-mono text-xs text-faint">{where}</span>}
    </span>
  );
}

async function tokenCall(body: object): Promise<{ token?: string; error?: string }> {
  const r = await fetch("/api/tokens", { method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Relic5-Request": "1" }, body: JSON.stringify(body) });
  return r.json();
}

/** Issue, rotate and revoke tokens for clients outside the tailnet. The secret is shown once, here, and never again. */
export function Tokens({ url }: { url: string }) {
  const p = usePoll<TokenRow[] | { error: string }>("/api/tokens", 0);
  const [name, setName] = useState("");
  const [expires, setExpires] = useState("90d");
  const [fresh, setFresh] = useState<{ name: string; token: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const act = async (body: { action: string; name: string; expires?: string }) => {
    setErr(null);
    const r = await tokenCall(body);
    if (r.error) setErr(r.error);
    else if (r.token) setFresh({ name: body.name, token: r.token });
    p.reload();
  };
  const rows = Array.isArray(p.data) ? p.data : [];
  const denied = p.data && !Array.isArray(p.data) ? p.data.error : null;
  return (
    <>
      <SectionHead>Tokens</SectionHead>
      <p className="m-0 px-5 pb-3 font-sans text-sm text-muted">
        For a client outside the tailnet. Stored hashed; the secret is shown once when issued. Only the hub itself and Nat's tailnet can manage them.
      </p>
      {denied ? <State error>{denied}</State> : (
        <form onSubmit={e => { e.preventDefault(); if (name) act({ action: "new", name, expires: expires === "never" ? "" : expires }); }}
          className="flex flex-wrap items-center gap-3 px-5 pb-4 font-sans">
          <input value={name} onChange={e => setName(e.target.value.toLowerCase())} placeholder="name, e.g. phone or laptop"
            pattern="[a-z0-9-]+" aria-label="Token name" className={inputCls + " w-64"} />
          <select value={expires} onChange={e => setExpires(e.target.value)} aria-label="Expires" className={inputCls}>
            <option value="30d">expires in 30 days</option><option value="90d">expires in 90 days</option>
            <option value="365d">expires in a year</option><option value="never">never expires</option>
          </select>
          <Btn primary type="submit" disabled={!name}>Issue token</Btn>
        </form>
      )}
      {err && <State error>{err}</State>}
      {fresh && (
        <div className="mx-5 mb-4 rounded-xl border border-warning p-4 font-sans">
          <div className="text-sm font-semibold text-text">Token for {fresh.name}: copy it now, it will not be shown again</div>
          <pre className="m-0 mt-2 overflow-x-auto rounded-lg bg-deep px-4 py-3 font-mono text-xs whitespace-pre-wrap text-soft select-all">{fresh.token}</pre>
          <pre className="m-0 mt-2 overflow-x-auto rounded-lg bg-deep px-4 py-3 font-mono text-xs whitespace-pre-wrap text-soft select-all">{`claude mcp add --transport http relic5 ${url} --header "Authorization: Bearer ${fresh.token}"\n# Codex:\nexport RELIC5_TOKEN=${fresh.token}\ncodex mcp add relic5 --url ${url} --bearer-token-env-var RELIC5_TOKEN`}</pre>
          <div className="mt-3 flex gap-2">
            <Btn type="button" onClick={() => navigator.clipboard.writeText(fresh.token)}>Copy the token</Btn>
            <Btn type="button" onClick={() => setFresh(null)}>Done, hide it</Btn>
          </div>
        </div>
      )}
      <DataTable rows={rows} rowKey={r => r.name} empty="no tokens yet" cols={[
        { key: "n", head: "name", cell: r => <b>{r.name}</b> },
        { key: "c", head: "created", cell: r => (r.created ? ago(r.created) : r.store) },
        { key: "l", head: "last used", cell: r => <LastUsedCell r={r} /> },
        { key: "e", head: "expires", cell: r => (r.expires ? bkk(r.expires) : r.store === "hashed" ? "never" : "") },
        { key: "r", head: "rotating", cell: r => (r.rotating_until ? `old one valid until ${bkk(r.rotating_until)}` : "") },
        { key: "a", head: "", cell: r => r.store === "hashed" ? (
          <span className="flex gap-2">
            <Btn type="button" onClick={() => act({ action: "rotate", name: r.name })}>Rotate</Btn>
            <Btn type="button" onClick={() => { if (confirm(`Revoke ${r.name}? Clients using it stop working at once.`)) act({ action: "revoke", name: r.name }); }}>Revoke</Btn>
          </span>) : <span className="text-faint">legacy file: edit it on the hub</span> },
      ]} />
    </>
  );
}

function Devices() {
  const p = usePoll<{ days: number; devices: Device[] }>("/api/clients", 30000);
  if (p.error && !p.data) return <State error>{p.error}</State>;
  const list = p.data?.devices ?? [];
  return (
    <>
      <SectionHead>Connected devices</SectionHead>
      <p className="m-0 px-5 pb-3 font-sans text-sm text-muted">
        Every machine (its door) and program (its client) that called this hub in the last {p.data?.days ?? 7} days, from the query log. The Mac shim shows as python-urllib (mcp), RelicFeeder as relic-feeder.
      </p>
      <DataTable rows={list} rowKey={d => d.door + d.client} empty="no calls yet" cols={[
        { key: "door", head: "door", cell: d => <Chip tone={d.door.startsWith("token") ? "warn" : "ok"}>{d.door}</Chip> },
        { key: "client", head: "client", cell: d => d.client },
        { key: "last", head: "last seen", cell: d => <span title={bkk(d.last)}>{ago(d.last)}</span> },
        { key: "c24", head: "calls 24 h", num: true, cell: d => num(d.calls_24h) },
        { key: "c", head: "calls 7 d", num: true, cell: d => num(d.calls) },
        { key: "tools", head: "tools", cell: d => Object.entries(d.tools).sort((a, b) => b[1] - a[1]).map(([t, n]) => `${t.replace("relic_", "")} ${n}`).join(" · ") },
        { key: "ms", head: "p50 ms", num: true, cell: d => d.p50_ms ?? "" },
      ]} />
    </>
  );
}

/** One prompt per tool, to paste into ChatGPT or Claude with relic5 connected (Nat, 2026-10-26: "let chat gpt help
 *  people to extract all stuff and visualize all stuff"). Each one was asked of ChatGPT on 2026-10-26. */
const ASK: Record<string, string> = {
  relic_hours: "What happened yesterday and so far today? Use relic5's relic_hours.",
  relic_month: "Give me every month since Sep 2025 in one line each, then October day by day.",
  relic_activity: "Chart my messages per month (typed by me vs the AI), and a weekday × hour heatmap of when I type.",
  relic_files: "Which files did the agents change most this month? Group them by project.",
  relic_readings: "What did z.ai say about yesterday afternoon, 15-minute windows, friction and lessons only?",
  relic_conversation: "Show me the whole conversation of session 008db2b3 with its tool calls, then summarize it.",
  relic_team: "Which projects ran on the same days in the last 30 days? Draw it as a timeline.",
  relic_oracles: "List my oracles by notes, then tell me who neo-oracle says it is.",
  relic_search: "Find where we decided to move the relic data to S3, and open the best hit.",
  relic_show: "Open relic5://2026-10/8522d25746ee880fb5a5d7a84a5788be with two messages around it.",
  relic_sessions: "List my sessions in relic5 from last week, grouped by repo.",
  relic_session: "What is session 008db2b3: its repo, size and subagents?",
  relic_asked: "What did I and my agents look for in relic5 today, and what was found?",
  relic_status: "Is the relic5 hub up to date? Any warnings?",
};

function WhatToAsk() {
  const [tools, setTools] = useState<Tool[] | null>(null);
  const [copied, setCopied] = useState("");
  useEffect(() => {
    fetch("/mcp", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/list" }) })
      .then(r => r.json()).then(j => setTools(j.result.tools)).catch(() => setTools([]));
  }, []);
  if (!tools?.length) return null;
  const ordered = [...tools].sort((a, b) => (a.name in ASK ? Object.keys(ASK).indexOf(a.name) : 99) - (b.name in ASK ? Object.keys(ASK).indexOf(b.name) : 99));
  return (
    <>
      <SectionHead sub={`The ${tools.length} tools this hub offers over MCP, each with something to ask once relic5 is connected in ChatGPT or Claude. Click a prompt to copy it.`}>What to ask</SectionHead>
      <div className="grid gap-3 lg:grid-cols-2">
        {ordered.map(t => (
          <div key={t.name} className="min-w-0 rounded-xl border border-line bg-panel px-5 py-4">
            <code className="font-mono text-sm font-semibold text-accent">{t.name}</code>
            <p className="m-0 mt-1.5 line-clamp-3 text-sm text-muted" title={t.description}>{t.description}</p>
            {ASK[t.name] && <button type="button" onClick={() => { navigator.clipboard.writeText(ASK[t.name]); setCopied(t.name); setTimeout(() => setCopied(""), 1500); }}
              className="mt-3 w-full rounded-lg border border-line bg-deep px-3 py-2 text-left text-sm text-soft hover:border-line-strong hover:text-text">
              {copied === t.name ? "Copied" : `“${ASK[t.name]}”`}</button>}
          </div>))}
      </div>
    </>
  );
}

export function ConnectView({ repo }: { repo?: string }) {
  const url = `${location.protocol}//${location.host}/mcp`;
  const shim = `${repo ?? "/opt/Code/github.com/Soul-Brews-Studio/relic5"}/.venv/bin/relic5`;
  const [test, setTest] = useState<{ ok: boolean; tools?: Tool[]; door?: string; error?: string } | null>(null);
  async function run() {
    setTest(null);
    try {
      const rpc = async (method: string, params?: object) => {
        const r = await fetch("/mcp", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, ...(params ? { params } : {}) }) });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return (await r.json()).result;
      };
      const tools: Tool[] = (await rpc("tools/list")).tools;
      const st = JSON.parse((await rpc("tools/call", { name: "relic_status", arguments: {} })).content[0].text);
      setTest({ ok: true, tools, door: st.you });
    } catch (e) { setTest({ ok: false, error: String((e as Error).message) }); }
  }
  return (
    <>
      <PageHead title="Connect" sub={<>relic5 is an MCP server: search, open, sessions, whole conversations, days hour by hour, months, activity counts for charts, files changed, model readings, oracles (the list is under What to ask). This hub's MCP address is <code className="font-mono text-sm text-soft">{url}</code>; on the tailnet no token is needed.</>}>
        <Btn primary type="button" onClick={run}>Test the connection</Btn>
      </PageHead>
      {test && <p className={cx("m-0 mb-6 text-sm", test.ok ? "text-ok" : "text-danger")}>{test.ok ? `Connected through the ${test.door} door · ${test.tools?.length} tools: ${test.tools?.map(t => t.name).join(", ")}` : `Failed: ${test.error}`}</p>}
      <div className="grid gap-4 xl:grid-cols-2">
      <Cmd title="Claude Code, over HTTP" why="From any machine on the tailnet. Keyword search (BM25, Thai-aware); semantic needs the shim below."
        cmd={`claude mcp add --transport http relic5 ${url}`} />
      <Cmd title="Claude Code on a Mac, with semantic search" why="The relic5 shim runs on the Mac, embeds a semantic query on its ANE (or MPS), and forwards everything to the hub. Needs the relic5 checkout on that Mac."
        cmd={`claude mcp add relic5 --env RELIC5_URL=${url.replace(/\/mcp$/, "")} -- ${shim} mcp`} />
      <Cmd title="Codex" why="Same address over HTTP. With a token: put it in an environment variable and pass its name."
        cmd={`codex mcp add relic5 --url ${url}\n# with a token (outside the tailnet):\ncodex mcp add relic5 --url ${url} --bearer-token-env-var RELIC5_TOKEN`} />
      <Cmd title="From outside the tailnet (a token)" why="Make a token on the hub, then pass it as a header. Tokens can be rotated or revoked: relic5 token list | rotate | revoke."
        cmd={`# on the hub:\nrelic5 token new <name>\n# on the client:\nclaude mcp add --transport http relic5 ${url} --header "Authorization: Bearer <token>"`} />
      <Cmd title="Check it" why="Lists the MCP servers Claude Code knows and whether each one answers."
        cmd={"claude mcp list\nclaude mcp get relic5"} />
      </div>
      <div className="mt-4 text-sm text-muted">
        Remove it again with <code className="font-mono">claude mcp remove relic5</code> or <code className="font-mono">codex mcp remove relic5</code>.
      </div>
      {test && !test.ok && <State error>{test.error}</State>}
      <WhatToAsk />
      <Tokens url={url} />
      <Devices />
    </>
  );
}
