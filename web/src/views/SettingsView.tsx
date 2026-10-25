// The hub's settings in one place (Nat, 2026-10-25: "we should have config/setting page?"): where the data lives
// (disk, S3, a mirror, a switch), who may reach the hub from outside the tailnet, and how this browser shows it.
import { StoragePanel } from "../components/StoragePanel";
import { Tokens } from "./ConnectView";
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
        <SectionHead sub="kept in this browser only">Appearance</SectionHead>
        <div className="flex flex-wrap items-center gap-x-8 gap-y-4 rounded-2xl border border-line bg-panel px-5 py-4">
          <label className="flex items-center gap-3 text-sm text-soft">Theme <Choice value={theme} set={setTheme} options={[["dark", "Dark"], ["paper", "Paper"]]} /></label>
          <label className="flex items-center gap-3 text-sm text-soft">Menu <Choice value={layout} set={setLayout} options={[["top", "Top bar"], ["side", "Sidebar"]]} /></label>
        </div>
      </section>
    </>
  );
}
