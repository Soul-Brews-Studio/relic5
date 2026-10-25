// A small Markdown renderer for memory notes and recaps: headings, paragraphs, lists, block quotes, fenced code, tables
// as plain rows, inline code, bold, italic and links. It builds React elements (never HTML strings), so a note can never
// inject markup. Styled the way the old ARRA Oracle Studio rendered a document (ui-oracle apps/studio DocDetail.tsx):
// accent headings, code on a tinted ground, 1.75 line height.
import type { ReactNode } from "react";
import { Marked } from "./ui";

function inline(text: string, q = "", key = 0): ReactNode[] {
  const plain = (t: string, k: number) => (q ? <Marked key={"m" + k} text={t} q={q} /> : t);
  const out: ReactNode[] = [];
  const re = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\s][^*]*\*)|(\[[^\]]+\]\((https?:\/\/[^)\s]+)\))/g;
  let last = 0, m: RegExpExecArray | null, n = key;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(plain(text.slice(last, m.index), n++));
    const t = m[0];
    if (m[1]) out.push(<code key={n++} className="rounded bg-accent-wash px-1.5 py-0.5 font-mono text-[0.9em] text-accent-ink">{t.slice(1, -1)}</code>);
    else if (m[2]) out.push(<strong key={n++} className="font-semibold text-text">{plain(t.slice(2, -2), n++)}</strong>);
    else if (m[3]) out.push(<em key={n++}>{plain(t.slice(1, -1), n++)}</em>);
    else if (m[4]) out.push(<a key={n++} href={m[5]} target="_blank" rel="noreferrer" className="text-accent underline">{t.slice(1, t.indexOf("]"))}</a>);
    last = m.index + t.length;
  }
  if (last < text.length) out.push(plain(text.slice(last), n++));
  return out;
}

/** Drop a leading YAML frontmatter block; the page shows its fields in the header instead. */
export const stripFrontmatter = (md: string) => md.replace(/^---\n[\s\S]*?\n---\n?/, "");

const plainTop = (t: string, q: string) => (q ? <Marked text={t} q={q} /> : t);
export function Markdown({ text, q = "", compact }: { text: string; q?: string; compact?: boolean }) {
  const lines = text.replace(/\r/g, "").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0, k = 0;
  while (i < lines.length) {
    const l = lines[i];
    if (/^<pasted_content\b/.test(l.trim())) {
      const body: string[] = [];
      for (i++; i < lines.length && !/^<\/pasted_content\b/.test(lines[i].trim()); i++) body.push(lines[i]);
      i++;
      blocks.push(<div key={k++} className="my-3 rounded-xl border border-line bg-deep px-4 py-3"><div className="mb-1 text-xs font-semibold text-muted">pasted</div>
        <div className="font-mono text-xs leading-relaxed whitespace-pre-wrap break-words text-soft">{plainTop(body.join("\n"), q)}</div></div>);
      continue;
    }
    if (/^```/.test(l)) {
      const body: string[] = [];
      for (i++; i < lines.length && !/^```/.test(lines[i]); i++) body.push(lines[i]);
      i++;
      blocks.push(<pre key={k++} className="my-4 overflow-x-auto rounded-xl border border-line bg-deep p-4 font-mono text-sm leading-relaxed whitespace-pre-wrap break-words text-soft">{body.join("\n")}</pre>);
      continue;
    }
    const h = /^(#{1,4})\s+(.*)$/.exec(l);
    if (h) {
      const size = h[1].length === 1 ? "text-lg" : h[1].length === 2 ? "text-lg" : "text-base";
      blocks.push(<h3 key={k++} className={`mt-8 mb-3 font-bold text-accent first:mt-0 ${size}`}>{inline(h[2], q)}</h3>);
      i++; continue;
    }
    if (/^\s*[-*]\s+/.test(l) || /^\s*\d+[.)]\s+/.test(l)) {
      const ordered = /^\s*\d/.test(l), items: string[] = [];
      for (; i < lines.length && (/^\s*[-*]\s+/.test(lines[i]) || /^\s*\d+[.)]\s+/.test(lines[i]) || /^\s{2,}\S/.test(lines[i])); i++) {
        if (/^\s{2,}\S/.test(lines[i]) && !/^\s*([-*]|\d+[.)])\s+/.test(lines[i]) && items.length) items[items.length - 1] += " " + lines[i].trim();
        else items.push(lines[i].replace(/^\s*([-*]|\d+[.)])\s+/, ""));
      }
      const L = ordered ? "ol" : "ul";
      blocks.push(<L key={k++} className={`my-4 flex flex-col gap-1.5 pl-6 ${ordered ? "list-decimal" : "list-disc"} marker:text-muted`}>{items.map((it, j) => <li key={j}>{inline(it, q)}</li>)}</L>);
      continue;
    }
    if (/^>\s?/.test(l)) {
      const qs: string[] = [];
      for (; i < lines.length && /^>\s?/.test(lines[i]); i++) qs.push(lines[i].replace(/^>\s?/, ""));
      blocks.push(<blockquote key={k++} className="my-4 rounded-xl bg-raised px-4 py-3 text-soft">{inline(qs.join(" "), q)}</blockquote>);
      continue;
    }
    if (/^\|.*\|\s*$/.test(l)) {
      const rows: string[][] = [];
      for (; i < lines.length && /^\|.*\|\s*$/.test(lines[i]); i++) if (!/^\|[\s:|-]+\|\s*$/.test(lines[i])) rows.push(lines[i].trim().slice(1, -1).split("|").map(c => c.trim()));
      blocks.push(
        <div key={k++} className="my-4 overflow-x-auto rounded-xl border border-line">
          <table className="w-full border-collapse text-sm">
            <tbody>{rows.map((r, j) => <tr key={j} className={j === 0 ? "bg-raised font-semibold text-text" : "border-t border-line"}>{r.map((c, x) => <td key={x} className="px-3 py-2 align-top">{inline(c, q)}</td>)}</tr>)}</tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (!l.trim()) { i++; continue; }
    const para: string[] = [];
    for (; i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|>|\s*[-*]\s+|\s*\d+[.)]\s+|\||\s*<\/?pasted_content)/.test(lines[i]); i++) para.push(lines[i]);
    blocks.push(<p key={k++} className={compact ? "my-1.5" : "my-3"}>{inline(para.join(" "), q)}</p>);
  }
  return <div className={compact ? "text-sm leading-[1.65] text-soft" : "text-base leading-[1.75] text-soft"}>{blocks}</div>;
}
