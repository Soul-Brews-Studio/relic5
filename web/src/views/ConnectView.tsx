import { useState } from "react";
import { usePoll } from "../api";
import { DataTable } from "../components/DataTable";
import { ago, bkk, num } from "../format";
import { Btn, Chip, cx, inputCls, SectionHead, State } from "../components/ui";

interface Device { door: string; client: string; first: string; last: string; calls: number; calls_24h: number;
                   tools: Record<string, number>; p50_ms: number | null }

/** How to connect an agent to this hub over MCP: native commands only, ready to copy (Nat, 2026-08-22, arra-memory:
 *  "use the native commands directly", not a wrapper), with this page's own address filled in, and a live test. */

interface Tool { name: string; description?: string }

function Cmd({ title, why, cmd }: { title: string; why: string; cmd: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="border-b border-line px-6 py-5 font-sans">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h3 className="m-0 text-[15px] font-semibold text-text">{title}</h3>
        <Btn type="button" onClick={() => { navigator.clipboard.writeText(cmd); setCopied(true); setTimeout(() => setCopied(false), 1500); }}>
          {copied ? "Copied" : "Copy"}
        </Btn>
      </div>
      <p className="m-0 mt-1 max-w-[80ch] text-[13px] text-muted">{why}</p>
      <pre className="m-0 mt-3 overflow-x-auto rounded-lg bg-deep px-4 py-3 font-mono text-[12px] leading-relaxed whitespace-pre-wrap text-soft select-all">{cmd}</pre>
    </div>
  );
}

interface TokenRow { name: string; created?: string; expires?: string | null; rotating_until?: string | null; store: string }

async function tokenCall(body: object): Promise<{ token?: string; error?: string }> {
  const r = await fetch("/api/tokens", { method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-Relic5-Request": "1" }, body: JSON.stringify(body) });
  return r.json();
}

/** Issue, rotate and revoke tokens for clients outside the tailnet. The secret is shown once, here, and never again. */
function Tokens({ url }: { url: string }) {
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
      <p className="m-0 px-5 pb-3 font-sans text-[13px] text-muted">
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
          <div className="text-[14px] font-semibold text-text">Token for {fresh.name}: copy it now, it will not be shown again</div>
          <pre className="m-0 mt-2 overflow-x-auto rounded-lg bg-deep px-4 py-3 font-mono text-[12px] whitespace-pre-wrap text-soft select-all">{fresh.token}</pre>
          <pre className="m-0 mt-2 overflow-x-auto rounded-lg bg-deep px-4 py-3 font-mono text-[12px] whitespace-pre-wrap text-soft select-all">{`claude mcp add --transport http relic5 ${url} --header "Authorization: Bearer ${fresh.token}"\n# Codex:\nexport RELIC5_TOKEN=${fresh.token}\ncodex mcp add relic5 --url ${url} --bearer-token-env-var RELIC5_TOKEN`}</pre>
          <div className="mt-3 flex gap-2">
            <Btn type="button" onClick={() => navigator.clipboard.writeText(fresh.token)}>Copy the token</Btn>
            <Btn type="button" onClick={() => setFresh(null)}>Done, hide it</Btn>
          </div>
        </div>
      )}
      <DataTable rows={rows} rowKey={r => r.name} empty="no tokens yet" cols={[
        { key: "n", head: "name", cell: r => <b>{r.name}</b> },
        { key: "c", head: "created", cell: r => (r.created ? ago(r.created) : r.store) },
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
      <p className="m-0 px-5 pb-3 font-sans text-[13px] text-muted">
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
      <div className="border-b border-line bg-panel px-6 pt-6 pb-5 font-sans">
        <h2 className="m-0 text-[22px] font-bold tracking-tight text-text">Connect an agent</h2>
        <p className="m-0 mt-1 max-w-[75ch] text-[14px] text-muted">
          relic5 is an MCP server with five tools (relic_search, relic_show, relic_sessions, relic_session, relic_status).
          This hub's MCP address is <code className="font-mono text-[13px] text-soft">{url}</code>. On the tailnet and on this machine no token is needed.
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Btn primary type="button" onClick={run}>Test the connection</Btn>
          {test && (test.ok
            ? <span className="text-[13px] text-accent">Connected through the {test.door} door · {test.tools?.length} tools: {test.tools?.map(t => t.name).join(", ")}</span>
            : <span className="text-[13px] text-danger">Failed: {test.error}</span>)}
        </div>
      </div>
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
      <div className={cx("px-6 py-4 font-sans text-[12px] text-faint")}>
        Remove it again with <code className="font-mono">claude mcp remove relic5</code> or <code className="font-mono">codex mcp remove relic5</code>.
      </div>
      {test && !test.ok && <State error>{test.error}</State>}
      <Tokens url={url} />
      <Devices />
    </>
  );
}
