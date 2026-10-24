// Shapes of the hub's GET routes (src/relic5/api.py). Optional fields are the ones a route may leave out; the UI shows
// "unknown" for those, never 0.

export interface JobEvent {
  job: string; verb: string; state: "start" | "progress" | "done" | "error"; at: string;
  pid?: number; host?: string; message?: string | null; rc?: number | null;
  done?: number | null; total?: number | null; unit?: string | null; who?: string;
}

export interface MachineFresh {
  newest_ts?: string; pushed_at?: string; lag_s?: number; push_age_s?: number; sync?: string;
}

export interface Layer { rows: number; bytes: number; newest_ts?: string; pushed_at?: string }

export interface Version {
  machine: string; at: string; os?: string; "push-format"?: number;
  "relic-scan"?: string; "relic-extract"?: string; "relic5-push"?: string;
}

export interface Month { month: string; sealed: boolean; rows: { text: number; thinking: number; tools: number } }

export interface Status {
  you: string; home: string; code: { name: string; version: string };
  layout?: { unit: string };
  watermarks: {
    index: { at: string | null; rows: number | null };
    fts: { at: string | null; rows: Record<string, number> };
    vectors: { at: string | null; pending: number | null; models?: Record<string, Record<string, { at: string; pending: number }>> };
  };
  months: { total: number; sealed: number; open: string; list: Month[] };
  freshness: { machines: Record<string, MachineFresh>; fts?: { at: string; age_s: number }; vectors?: { at: string } };
  store: {
    parts: Record<string, Record<string, number>>; search: Record<string, number>; vectors: Record<string, number>;
    logs: number; search_total: number; total: number; manifests: number;
    disk: { total: number; used: number; free: number; free_pct: number };
    growth?: { per_day: number | null; since: string };
  };
  resources: {
    load: number[]; cpus: number; memory?: { total: number; available: number };
    process?: { rss: number; threads: number; open_files: number }; container?: { memory: number };
  };
  machines: Record<string, Record<string, Layer>>;
  versions: Record<string, Version>;
  rows: Record<string, number | null>;
  jobs: { running: JobEvent[]; recent: JobEvent[]; last_error: JobEvent | null };
  backup?: { at: string | null; bytes: number | null; message: string | null; age_s: number | null; host: string | null };
  warnings: string[];
}

export interface Hit {
  uid: string; partition: string; session_uuid: string; role: string; ts: string; repo_key?: string;
  session_name?: string | null; title?: string | null; text_snippet: string; score: number; layer: string;
  machines: string[]; link: string;
}

export interface SearchResult {
  hits: Hit[]; horizon: string; horizons_tried: string[]; searched_months: string[]; widened?: boolean; fallback?: string;
}

export interface Msg { ts: string; role: string; text: string; machines?: string[]; sid?: string }
export interface ShowResult { before: Msg[]; target: Msg; after: Msg[]; link: string }

export interface TailRow { ts_th?: string; machines?: string[]; role: string; session_name?: string; sid?: string; text?: string; uid?: string }
export interface TailResult { rows: TailRow[]; newest?: string }

export interface QueryRow {
  at: string; door: string; tool: string; query: string; client?: string; ms?: number; hits?: number | null;
  mode?: string | null; horizon?: string | null; vector?: boolean; error?: string | null; for_s?: number;
}
export interface Queries {
  running: QueryRow[]; last: QueryRow[]; per_hour: Record<string, { n: number; p50_ms: number; p95_ms: number }>;
  top: { query: string; n: number }[]; zero_hits: QueryRow[];
}

export interface EvalRow {
  file: string; method: string; n: number; "recall@10": number; "precision@10": number; mrr: number;
  p50_ms: number; p95_ms: number; misses?: string[]; at: string;
}
