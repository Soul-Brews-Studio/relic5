import { useEffect, useRef, type ReactNode } from "react";
import { Btn } from "./ui";

/** A native <dialog>: Escape, focus containment and focus return come from the browser (Structor's record drawer). */
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
    <dialog ref={ref} onClose={onClose}
      className="m-auto h-[min(80vh,900px)] w-[min(980px,94vw)] rounded-[5px] border border-line-strong bg-panel p-0 text-text shadow-2xl">
      <div className="grid h-full grid-rows-[auto_minmax(0,1fr)_auto]">
        <header className="flex items-baseline gap-3 border-b border-line px-4 py-3">
          <h2 className="m-0 min-w-0 flex-1 truncate font-sans text-sm font-semibold">{title}</h2>
          <Btn type="button" onClick={onClose}>Close</Btn>
        </header>
        <div className="overflow-auto pb-4">{children}</div>
        <footer className="flex items-center justify-between gap-2 border-t border-line px-4 py-2.5 text-[11px] text-muted">
          <span className="min-w-0 truncate">{note}</span>
          {onCopy && <Btn type="button" onClick={onCopy}>Copy link</Btn>}
        </footer>
      </div>
    </dialog>
  );
}
