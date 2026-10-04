import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

const API_URL = process.env.API_URL ?? "http://localhost:8000"

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  server: {
    // Let `./dev ngrok` reach the dev server. Vite blocks unknown hosts.
    allowedHosts: [".ngrok-free.app", ".ngrok-free.dev", ".ngrok.app"],
    // Send requests under /api/ to the backend. The backend serves every
    // route under /api, but for the OAuth metadata of its MCP server, which
    // clients look for under /.well-known/ at the root. The Host header is
    // kept, so the addresses the backend writes into that metadata are the
    // ones the client used, such as the ngrok URL, not the backend's own.
    proxy: {
      "/api": { target: API_URL, changeOrigin: false },
      "/.well-known": { target: API_URL, changeOrigin: false },
    },
  },
})
