// The pet-studio server's API (server/index.ts).
export type Job = {
  id: string; kind: string; title: string; status: "queued" | "running" | "ok" | "failed";
  started: number; ended?: number; log?: string[]; last?: string; result?: any; error?: string;
  progress?: number; waitingFor?: string;
};
export type Pack = { name: string; builtIn: boolean; bytes: number; files: { name: string; bytes: number; url: string }[] };
export type State = {
  oraclePet: { running: boolean; at?: string };
  pets: { name: string; link?: string; firmware?: string; pack?: string; app?: string; ota?: string }[];
  ports: string[];
  boards: Record<string, { label: string; project: string }>;
  firmware: { board: string; label: string; project: string; built: string | null; bytes: number }[];
  apps: { name: string; bytes: number; url: string }[];
  packs: Pack[];
  sources: string[];
  jobs: Job[];
};

async function call<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, body === undefined ? undefined : {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
  });
  const d = await r.json();
  if (!r.ok) throw new Error(d.error ?? r.statusText);
  return d as T;
}

export const api = {
  state: () => call<State>("/api/state"),
  job: (id: string) => call<Job>(`/api/jobs/${id}`),
  source: (name: string) => call<{ name: string; lang: string; source: string }>(`/api/apps/${name}/source`),
  buildApp: (name: string, lang: string, source: string) => call<{ job: string }>("/api/apps/build", { name, lang, source }),
  createPack: (b: { name: string; imageBase64?: string; imageExt?: string; prompt?: string }) => call<{ job: string }>("/api/packs/create", b),
  buildFirmware: (board: string, pack: string) => call<{ job: string }>("/api/firmware/build", { board, pack }),
  flashBle: (b: { kind: string; name?: string; board?: string; pet?: string }) => call<{ job: string }>("/api/flash/ble", b),
  flashUsb: (board: string, port: string) => call<{ job: string }>("/api/flash/usb", { board, port }),
};
