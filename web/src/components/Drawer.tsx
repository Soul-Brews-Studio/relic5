import { useEffect, useRef, useState, type ReactNode } from "react";
import { Btn } from "./ui";
import { Close } from "./Icons";

/** A native <dialog>: Escape, focus containment and focus return come from the browser. 16px corners like every card. */
export function Drawer({ open, title, note, onClose, onCopy, children }: {
  open: boolean; title: ReactNode; note?: ReactNode; onClose: () => void; onCopy?: () => void; children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} onClose={onClose} onClick={e => e.target === ref.current && onClose()} aria-labelledby="drawer-title"
      className="m-auto h-[min(84vh,920px)] w-[min(1000px,94vw)] rounded-2xl border border-line-strong bg-panel p-0 text-text shadow-[var(--shadow-pop)]">
      <div className="grid h-full grid-rows-[auto_minmax(0,1fr)_auto]">
        <header className="flex items-center gap-3 border-b border-line py-2 pr-2 pl-6">
          <h2 id="drawer-title" className="m-0 min-w-0 flex-1 truncate text-base font-bold">{title}</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="grid size-11 place-items-center rounded-lg text-muted hover:bg-raised hover:text-text"><Close size={18} /></button>
        </header>
        <div className="overflow-auto">{children}</div>
        <footer className="flex items-center justify-between gap-3 border-t border-line px-6 py-3 text-xs text-muted">
          <span className="min-w-0 truncate font-mono">{note}</span>
          {onCopy && <CopyBtn onCopy={onCopy} />}
        </footer>
      </div>
    </dialog>
  );
}

function CopyBtn({ onCopy }: { onCopy: () => void }) {
  const [done, setDone] = useState(false);
  return <Btn type="button" onClick={() => { onCopy(); setDone(true); setTimeout(() => setDone(false), 2000); }}>{done ? "Copied" : "Copy link"}</Btn>;
}
