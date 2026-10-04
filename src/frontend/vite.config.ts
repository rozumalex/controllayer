import path from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

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
    // route under /api.
    proxy: {
      "/api": process.env.API_URL ?? "http://localhost:8000",
    },
  },
})
