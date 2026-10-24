import type { ReactNode } from "react";
import { Moon, Sun } from "./Icons";

export type Theme = "dark" | "paper";

/** The one top bar, on the glance page and the hub: wordmark, when the hub was last read, theme, one link. */
export function TopBar({ note, theme, setTheme, link }:
  { note: ReactNode; theme: Theme; setTheme: (t: Theme) => void; link: ReactNode }) {
  return (
    <header className="sticky top-0 z-10 border-b border-line bg-[color-mix(in_srgb,var(--bg)_88%,transparent)] backdrop-blur-sm">
      <div className="mx-auto flex max-w-[1200px] items-center gap-4 px-5 py-3 font-sans">
        <a href="#" className="text-[17px] font-bold text-accent">relic<span className="text-faint">5</span></a>
        <span className="hidden min-w-0 truncate text-[13px] text-muted sm:inline">{note}</span>
        <button type="button" onClick={() => setTheme(theme === "dark" ? "paper" : "dark")} aria-label={`Switch to ${theme === "dark" ? "Paper" : "Dark"}`}
          className="ml-auto grid size-9 flex-none place-items-center rounded-full border border-line text-soft hover:border-line-strong hover:text-text">
          {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
        </button>
        {link}
      </div>
    </header>
  );
}

export const pill = "flex flex-none items-center gap-1.5 rounded-full border border-line px-4 py-1.5 text-[13px] font-semibold text-soft hover:border-line-strong hover:text-text";
