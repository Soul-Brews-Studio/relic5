import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The build lands inside the Python package, so the hub serves plain static files and white needs no Node.
// `bun run dev` proxies /api to a hub (RELIC5_DEV_HUB, default the local one on 8795).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "./",
  build: { outDir: "../src/relic5/web", emptyOutDir: true, assetsDir: "assets" },
  server: { host: "127.0.0.1", port: 5275, proxy: { "/api": { target: process.env.RELIC5_DEV_HUB ?? "http://127.0.0.1:8795", changeOrigin: true } } },
});
