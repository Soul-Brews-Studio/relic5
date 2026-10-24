// A small Markdown renderer for memory notes and recaps: headings, paragraphs, lists, block quotes, fenced code, tables
// as plain rows, inline code, bold, italic and links. It builds React elements (never HTML strings), so a note can never
// inject markup. Styled the way the old ARRA Oracle Studio rendered a document (ui-oracle apps/studio DocDetail.tsx):
// accent headings, code on a tinted ground, 1.75 line height.
import type { ReactNode } from "react";

function inline(text: string, key = 0): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\*[^*\s][^*]*\*)|(\[[^\]]+\]\((https?:\/\/[^)\s]+)\))/g;
  let last = 0, m: RegExpExecArray | null, n = key;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const t = m[0];
    if (m[1]) out.push(<code key={n++} className="rounded bg-accent-wash px-1.5 py-0.5 font-mono text-[0.9em] text-accent-ink">{t.slice(1, -1)}</code>);
    else if (m[2]) out.push(<strong key={n++} className="font-semibold text-text">{t.slice(2, -2)}</strong>);
    else if (m[3]) out.push(<em key={n++}>{t.slice(1, -1)}</em>);
    else if (m[4]) out.push(<a key={n++} href={m[5]} target="_blank" rel="noreferrer" className="text-accent underline">{t.slice(1, t.indexOf("]"))}</a>);
    last = m.index + t.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

/** Drop a leading YAML frontmatter block; the page shows its fields in the header instead. */
export const stripFrontmatter = (md: string) => md.replace(/^---\n[\s\S]*?\n---\n?/, "");

export function Markdown({ text }: { text: string }) {
  const lines = text.replace(/\r/g, "").split("\n");
  const blocks: ReactNode[] = [];
  let i = 0, k = 0;
  while (i < lines.length) {
    const l = lines[i];
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
      blocks.push(<h3 key={k++} className={`mt-8 mb-3 font-bold text-accent first:mt-0 ${size}`}>{inline(h[2])}</h3>);
      i++; continue;
    }
    if (/^\s*[-*]\s+/.test(l) || /^\s*\d+[.)]\s+/.test(l)) {
      const ordered = /^\s*\d/.test(l), items: string[] = [];
      for (; i < lines.length && (/^\s*[-*]\s+/.test(lines[i]) || /^\s*\d+[.)]\s+/.test(lines[i]) || /^\s{2,}\S/.test(lines[i])); i++) {
        if (/^\s{2,}\S/.test(lines[i]) && !/^\s*([-*]|\d+[.)])\s+/.test(lines[i]) && items.length) items[items.length - 1] += " " + lines[i].trim();
        else items.push(lines[i].replace(/^\s*([-*]|\d+[.)])\s+/, ""));
      }
      const L = ordered ? "ol" : "ul";
      blocks.push(<L key={k++} className={`my-4 flex flex-col gap-1.5 pl-6 ${ordered ? "list-decimal" : "list-disc"} marker:text-muted`}>{items.map((it, j) => <li key={j}>{inline(it)}</li>)}</L>);
      continue;
    }
    if (/^>\s?/.test(l)) {
      const q: string[] = [];
      for (; i < lines.length && /^>\s?/.test(lines[i]); i++) q.push(lines[i].replace(/^>\s?/, ""));
      blocks.push(<blockquote key={k++} className="my-4 rounded-xl bg-raised px-4 py-3 text-soft">{inline(q.join(" "))}</blockquote>);
      continue;
    }
    if (/^\|.*\|\s*$/.test(l)) {
      const rows: string[][] = [];
      for (; i < lines.length && /^\|.*\|\s*$/.test(lines[i]); i++) if (!/^\|[\s:|-]+\|\s*$/.test(lines[i])) rows.push(lines[i].trim().slice(1, -1).split("|").map(c => c.trim()));
      blocks.push(
        <div key={k++} className="my-4 overflow-x-auto rounded-xl border border-line">
          <table className="w-full border-collapse text-sm">
            <tbody>{rows.map((r, j) => <tr key={j} className={j === 0 ? "bg-raised font-semibold text-text" : "border-t border-line"}>{r.map((c, x) => <td key={x} className="px-3 py-2 align-top">{inline(c)}</td>)}</tr>)}</tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (!l.trim()) { i++; continue; }
    const para: string[] = [];
    for (; i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|>|\s*[-*]\s+|\s*\d+[.)]\s+|\|)/.test(lines[i]); i++) para.push(lines[i]);
    blocks.push(<p key={k++} className="my-3">{inline(para.join(" "))}</p>);
  }
  return <div className="text-base leading-[1.75] text-soft">{blocks}</div>;
}
