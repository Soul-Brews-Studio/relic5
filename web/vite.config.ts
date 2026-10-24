import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The build lands inside the Python package, so the hub serves plain static files and white needs no Node.
// `bun run dev` proxies /api to a hub (RELIC5_DEV_HUB, default the local one on 8795).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // Preact through its React-compatible layer: the same code, about a third of the JavaScript (a phone over tailscale).
  // react-dom/client is aliased too, so createRoot and flushSync resolve to preact/compat.
  resolve: { alias: { "react-dom/test-utils": "preact/test-utils", "react-dom/client": "preact/compat/client", "react-dom": "preact/compat", "react/jsx-runtime": "preact/jsx-runtime", "react/jsx-dev-runtime": "preact/jsx-dev-runtime", react: "preact/compat" } },
  base: "./",
  build: { outDir: "../src/relic5/web", emptyOutDir: true, assetsDir: "assets" },
  server: { host: "127.0.0.1", port: 5275, proxy: { "/api": { target: process.env.RELIC5_DEV_HUB ?? "http://127.0.0.1:8795", changeOrigin: true } } },
});
