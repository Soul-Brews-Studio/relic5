// Where the hub keeps its data, and a second home for it (Nat, 2026-10-25: "ui config local / s3 / mirror / or
// switch?"). The hub runs on a disk folder or an S3 prefix (store.py); a mirror copies its data to the other kind on
// a clock; a switch, only after a verify with nothing missing, moves the hub there at its next start (mirror.py).
// Changes are allowed from the hub itself or Nat's tailnet, never with a token (GET/POST /api/storage).
import { useState } from "react";
import { post, usePoll } from "../api";
import { ago, bkk, bytes, num } from "../format";
import { Btn, Chip, inputCls, Lbl, State } from "./ui";

interface Verify { ok: boolean; files: number; bytes: number; on_dst: number; missing: number; differ: number; behind?: number; examples: string[]; at: string; dst: string }
interface Storage {
  root: string; kind: "disk" | "s3"; endpoint: string | null; cache: string | null; mirror: string | null; every_min: number;
  switch_to: string | null; switched_from: string | null; verify: Verify | null;
  state: { running: { dst: string; done: number; total: number | null; at: string } | null; last?: { files?: number; bytes?: number; skipped?: number; seconds?: number; errors?: string[]; at: string; error?: string } };
  last_job: { state: string; at: string; message?: string } | null;
}

const kindOf = (p: string | null) => (!p ? "" : p.startsWith("s3://") ? "S3" : "disk");

export function StoragePanel() {
  const p = usePoll<Storage>("/api/storage", 5000);
  const [target, setTarget] = useState(""), [every, setEvery] = useState("");
  const [busy, setBusy] = useState(""), [msg, setMsg] = useState<string | null>(null);
  const act = async (body: Record<string, unknown>, label: string) => {
    setBusy(label); setMsg(null);
    try { const r = await post<Record<string, unknown>>("/api/storage", body); p.reload(); return r; }
    catch (e) { setMsg(String((e as Error).message)); } finally { setBusy(""); }
  };
  if (p.error && !p.data) return <State error>{p.error}</State>;
  if (!p.data) return null;
  const s = p.data, run = s.state.running, v = s.verify, other = s.kind === "s3" ? "a disk folder: /data/mirror" : "s3://relic5-live/hub";
  return (
    <section aria-label="Storage" className="mb-10 rounded-2xl border border-line bg-panel">
      <div className="grid gap-px overflow-hidden rounded-2xl bg-line md:grid-cols-2">
        <div className="bg-panel p-5">
          <Lbl>the hub lives on</Lbl>
          <div className="mt-2 flex items-center gap-2"><Chip tone="live">{s.kind === "s3" ? "S3" : "disk"}</Chip><code className="min-w-0 truncate font-mono text-sm text-text" title={s.root}>{s.root}</code></div>
          <p className="m-0 mt-2 text-sm text-muted">{s.kind === "s3" ? <>Parts, logs and the index are objects at {s.endpoint}; maps and the index lock are kept locally in <code className="font-mono text-xs">{s.cache}</code>.</> : <>A folder on this machine's disk.</>}
            {s.switched_from && <> Switched here from <code className="font-mono text-xs">{s.switched_from}</code>, which is now the mirror.</>}</p>
        </div>
        <div className="bg-panel p-5">
          <Lbl>mirror</Lbl>
          {s.mirror ? <>
            <div className="mt-2 flex items-center gap-2"><Chip>{kindOf(s.mirror)}</Chip><code className="min-w-0 truncate font-mono text-sm text-text" title={s.mirror}>{s.mirror}</code></div>
            <p className="m-0 mt-2 text-sm text-muted">Copied every {s.every_min} min; only what changed moves, nothing is ever deleted there.
              {run ? <> <b className="text-accent">Copying now:</b> {num(run.done)}{run.total != null && ` of ${num(run.total)}`} files.</>
                : s.state.last?.error ? <> <span className="text-danger">Last run failed: {s.state.last.error}</span></>
                : s.last_job ? <> Last run {ago(s.last_job.at)}: {s.last_job.message ?? s.last_job.state}.</> : <> No run yet.</>}</p>
          </> : <p className="m-0 mt-2 text-sm text-muted">None yet. A mirror keeps a second copy of the hub's data, on S3 for a disk hub or on a disk for an S3 one, and makes a switch possible.</p>}
        </div>
      </div>

      <div className="border-t border-line p-5">
        <form className="flex flex-wrap items-end gap-3" onSubmit={e => { e.preventDefault(); act({ action: "set-mirror", target: target.trim(), every_min: Number(every) || undefined }, "set").then(r => r && setTarget("")); }}>
          <label className="flex min-w-0 flex-1 flex-col gap-1 text-xs font-semibold text-muted">mirror to
            <input value={target} onChange={e => setTarget(e.target.value)} placeholder={s.mirror ?? other} className={inputCls + " w-full font-mono text-sm"} /></label>
          <label className="flex w-28 flex-col gap-1 text-xs font-semibold text-muted">every (min)
            <input value={every} onChange={e => setEvery(e.target.value)} inputMode="numeric" placeholder={String(s.every_min)} className={inputCls + " w-full"} /></label>
          <Btn type="submit" disabled={!!busy || (!target.trim() && !every)}>{s.mirror ? "Change" : "Set mirror"}</Btn>
          {s.mirror && <Btn type="button" disabled={!!busy || !!run} onClick={() => act({ action: "mirror-now" }, "now")}>{run ? "Copying…" : "Mirror now"}</Btn>}
          {s.mirror && <Btn type="button" disabled={!!busy} onClick={() => act({ action: "verify" }, "verify")}>{busy === "verify" ? "Checking…" : "Verify"}</Btn>}
          {s.mirror && <Btn type="button" disabled={!!busy} onClick={() => confirm(`Stop mirroring to ${s.mirror}? The copy there stays.`) && act({ action: "set-mirror", target: "" }, "off")}>Stop</Btn>}
        </form>
        {msg && <p role="alert" className="m-0 mt-3 text-sm text-danger">{msg}</p>}

        {v && (
          <div className={"mt-4 rounded-xl px-4 py-3 text-sm " + (v.ok ? "bg-ok-wash text-soft" : "bg-warning-wash text-soft")}>
            <b className={v.ok ? "text-ok" : "text-warning"}>{v.ok ? "Verified" : "Not complete"}</b> {bkk(v.at)}: {num(v.files)} files ({bytes(v.bytes)}) here, {num(v.on_dst)} on the mirror
            {v.ok ? "; every data file is there at the same size." : `; ${v.missing} missing, ${v.differ} differ.`}
            {!!v.behind && <> {num(v.behind)} log and index files are behind, which a running hub always is.</>}
            {!v.ok && !!v.examples.length && <code className="mt-1 block font-mono text-xs text-muted">{v.examples.slice(0, 3).join(" · ")}</code>}
          </div>
        )}

        {s.mirror && (
          <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-line pt-4 text-sm">
            {s.switch_to ? <>
              <span className="text-text">At its next start the hub moves to <code className="font-mono">{s.switch_to}</code>; <code className="font-mono">{s.root}</code> becomes the mirror.</span>
              <span className="text-muted">Restart it on white: <code className="font-mono">just up</code></span>
              <Btn type="button" onClick={() => act({ action: "cancel-switch" }, "cancel")}>Cancel the switch</Btn>
            </> : <>
              <span className="text-muted">Switch the hub to the mirror: it takes effect at the next start, and only after a clean verify.</span>
              <Btn type="button" disabled={!v?.ok || !!busy} onClick={() => confirm(`Move the hub to ${s.mirror} at its next start?`) && act({ action: "switch" }, "switch")}>Switch at next start</Btn>
            </>}
          </div>
        )}
      </div>
    </section>
  );
}
