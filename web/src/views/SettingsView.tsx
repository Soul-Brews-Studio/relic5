// The hub's settings in one place (Nat, 2026-10-25: "we should have config/setting page?"): where the data lives
// (disk, S3, a mirror, a switch), who may reach the hub from outside the tailnet, and how this browser shows it.
import { useState } from "react";
import { usePoll } from "../api";
import { StoragePanel } from "../components/StoragePanel";
import { DataTable } from "../components/DataTable";
import { LastUsedCell, Tokens, type LastUsed } from "./ConnectView";
import { PageHead, SectionHead } from "../components/ui";
import { cx } from "../components/ui";
import type { Layout, Theme } from "../components/Shell";

function Choice<T extends string>({ value, set, options }: { value: T; set: (v: T) => void; options: [T, string][] }) {
  return (
    <div role="radiogroup" className="inline-flex rounded-xl border border-line bg-deep p-1">
      {options.map(([v, label]) => (
        <button key={v} type="button" role="radio" aria-checked={value === v} onClick={() => set(v)}
          className={cx("min-h-9 rounded-lg px-3 text-sm font-semibold", value === v ? "bg-raised text-text" : "text-muted hover:text-text")}>{label}</button>
      ))}
    </div>
  );
}

interface Conn extends LastUsed { client_id: string; name: string; at: string; redirect_uris: string[]; tokens: number }

/** claude.ai and other OAuth clients connected through the tunnel (oauth.py), each revocable. */
function Connectors() {
  const p = usePoll<{ clients: Conn[]; public: string | null } | { error: string }>("/api/oauth", 0);
  const [gone, setGone] = useState<string[]>([]);
  if (!p.data) return <p className="m-0 text-sm text-muted">Reading…</p>;
  if ("error" in p.data) return <p className="m-0 text-sm text-muted">{p.data.error}</p>;
  const { clients, public: pub } = p.data;
  const revoke = async (id: string) => {
    await fetch("/api/oauth", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-Relic5-Request": "1" }, body: JSON.stringify({ client_id: id }) });
    setGone(g => [...g, id]);
  };
  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-2xl border border-line bg-panel px-5 py-4 text-sm text-soft">
        {pub ? <>In claude.ai: Settings, Connectors, Add custom connector. In ChatGPT: Settings, Apps, Advanced settings, Developer mode, Create app, authentication OAuth. URL <code className="font-mono text-text select-all">{pub}/mcp</code>. Either opens this hub's approve page; paste one of the access tokens above to let it in.</>
          : <>No public address: set RELIC5_PUBLIC_URL to the tunnel's https address to connect claude.ai or ChatGPT.</>}
      </div>
      <DataTable rows={clients.filter(c => !gone.includes(c.client_id))} rowKey={c => c.client_id} empty="No connector has been approved yet." cols={[
        { key: "n", head: "connector", lead: true, cell: c => <b>{c.name}</b>, title: c => c.redirect_uris.join(", ") },
        { key: "a", head: "registered", w: "w-44", cell: c => <span className="tabular-nums text-muted">{c.at.slice(0, 16).replace("T", " ")}</span> },
        { key: "l", head: "last used", w: "w-56", cell: c => <LastUsedCell r={c} /> },
        { key: "t", head: "live tokens", num: true, w: "w-24", cell: c => c.tokens },
        { key: "r", head: "", w: "w-24", cell: c => <button type="button" onClick={() => revoke(c.client_id)} className="min-h-9 rounded-lg px-2 text-xs font-semibold text-danger hover:bg-raised">Revoke</button> },
      ]} />
    </div>
  );
}

export function SettingsView({ theme, setTheme, layout, setLayout }: { theme: Theme; setTheme: (t: Theme) => void; layout: Layout; setLayout: (l: Layout) => void }) {
  const url = `${location.protocol}//${location.host}/mcp`;
  return (
    <>
      <PageHead title="Settings" sub="Where the hub keeps its data, who can reach it from outside the tailnet, and how this browser shows it." />
      <section className="mb-10">
        <SectionHead sub="the hub's data: a folder on its disk or an s3:// prefix; a mirror kept in step; a switch at the next start">Storage</SectionHead>
        <StoragePanel />
      </section>
      <section className="mb-10">
        <SectionHead sub="for clients outside the tailnet; on the tailnet no token is needed">Access tokens</SectionHead>
        <Tokens url={url} />
      </section>
      <section className="mb-10">
        <SectionHead sub="claude.ai, ChatGPT and other apps that reach /mcp through the tunnel with OAuth; revoking one ends its tokens at once">Connectors</SectionHead>
        <Connectors />
      </section>
      <section className="mb-10">
        <SectionHead sub="kept in this browser only">Appearance</SectionHead>
        <div className="flex flex-wrap items-center gap-x-8 gap-y-4 rounded-2xl border border-line bg-panel px-5 py-4">
          <label className="flex items-center gap-3 text-sm text-soft">Theme <Choice value={theme} set={setTheme} options={[["dark", "Dark"], ["paper", "Paper"]]} /></label>
          <label className="flex items-center gap-3 text-sm text-soft">Menu <Choice value={layout} set={setLayout} options={[["top", "Top bar"], ["side", "Sidebar"]]} /></label>
        </div>
      </section>
    </>
  );
}
