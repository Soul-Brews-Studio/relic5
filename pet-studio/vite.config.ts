import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { resolve } from "node:path";

// `bun run dev`: Vite on :5174 with /api proxied to the server (bun run server, :4810).
// `bun run build`: web/ -> dist/, which the server serves itself at http://127.0.0.1:4810.
export default defineConfig({
  root: "web",
  plugins: [react(), tailwindcss()],
  // two pages: index.html (v1: blocks, code, firmware) and v2.html (the designer)
  build: { outDir: "../dist", emptyOutDir: true, sourcemap: true, rollupOptions: { input: { main: resolve(import.meta.dirname, "web/index.html"), v2: resolve(import.meta.dirname, "web/v2.html") } } },
  server: { host: "127.0.0.1", port: 5174, proxy: { "/api": "http://127.0.0.1:4810" } },
});
