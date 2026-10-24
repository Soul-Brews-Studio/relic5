import type { Tone } from "./ui";

/** A machine's relic-chain verdict, "2026-10-24 07:44:42 SYNC OK  text|…" -> tone and the time. */
export function syncChip(line?: string): { tone: Tone; text: string } {
  if (!line) return { tone: "dim", text: "no chain log" };
  const t = line.slice(11, 16);
  return line.includes("MISMATCH") ? { tone: "bad", text: `MISMATCH ${t}` } : { tone: "ok", text: `SYNC ${t}` };
}
