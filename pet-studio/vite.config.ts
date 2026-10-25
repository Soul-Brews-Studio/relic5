import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { resolve } from "node:path";

// `bun run dev`: Vite on :5174 with /api proxied to the server (bun run server, :4810).
// `bun run build`: web/ -> dist/, which the server serves itself at http://127.0.0.1:4810.
export default defineConfig({
  root: "web",
  plugins: [react(), tailwindcss()],
  // one page in relic5: v2.html, the designer canvas (Nat, 2026-10-21: "studio v2 but no block please"; 2026-10-24:
  // "it should only graphic canvas not blockly"). Blocks, apps and firmware stay on the server API and the MCP tools.
  build: { outDir: "../dist", emptyOutDir: true, sourcemap: true, rollupOptions: { input: { v2: resolve(import.meta.dirname, "web/v2.html") } } },
  server: { host: "127.0.0.1", port: 5174, proxy: { "/api": "http://127.0.0.1:4810" } },
});
