// Formatting. Every helper returns "unknown" for a missing value, never 0 (relic3 app/PRODUCT.md).

export const UNKNOWN = "unknown";

export const num = (v: number | null | undefined) => (v == null ? UNKNOWN : Number(v).toLocaleString());

export const bytes = (b: number | null | undefined) =>
  b == null ? UNKNOWN : b > 1e9 ? (b / 1e9).toFixed(2) + " GB" : b > 1e6 ? (b / 1e6).toFixed(1) + " MB" : (b / 1e3).toFixed(0) + " kB";

export const secs = (v: number | null | undefined) =>
  v == null ? UNKNOWN : v < 120 ? `${Math.round(v)} s` : v < 7200 ? `${Math.round(v / 60)} min` : v < 172800 ? `${Math.round(v / 3600)} h` : `${Math.round(v / 86400)} d`;

export const ago = (iso: string | null | undefined) => {
  if (!iso) return UNKNOWN;
  const t = Date.parse(iso);
  return Number.isNaN(t) ? UNKNOWN : secs((Date.now() - t) / 1000) + " ago";
};

/** "2026-10-24T01:07:47Z" -> "10-24 08:07" in Bangkok time, the fleet's clock. */
export const bkk = (iso: string | null | undefined) => {
  if (!iso) return UNKNOWN;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return iso;
  return new Date(t + 7 * 3600e3).toISOString().slice(5, 16).replace("T", " ");
};

export const sum = (o: Record<string, number> | undefined) => Object.values(o ?? {}).reduce((a, b) => a + b, 0);

/** 2002706 -> "2.00M", 869323 -> "869k": for big numerals in narrow cards; the exact number goes in a title. */
export const compact = (v: number | null | undefined) =>
  v == null ? UNKNOWN : v >= 1e6 ? (v / 1e6).toFixed(2) + "M" : v >= 1e4 ? Math.round(v / 1e3) + "k" : Number(v).toLocaleString();

/** One clock for the whole hub: 24-hour Bangkok-style "22:10", the same as the tables (Panel A: "10:18:18 PM" vs "22:10"). */
export const clock = (d: Date | null | undefined) => (d ? d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" }) : UNKNOWN);

/** Each repo keeps one colour everywhere (Nat loves colour-coded decks, one accent per project: memory design-deck-style,
 *  2026-06-27). Ten hues on the dark ground, all readable as text; the same name always lands on the same hue. */
const REPO_HUES = ["#64b5f6", "#f5b73b", "#6fd6a0", "#c792ea", "#ff8a65", "#4dd0e1", "#f48fb1", "#aed581", "#ffd54f", "#9fa8da"];
export const repoColor = (name: string | null | undefined) => {
  let h = 0;
  for (const c of name ?? "") h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return REPO_HUES[h % REPO_HUES.length];
};
