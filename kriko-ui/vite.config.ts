import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the page asks its own origin for `/api/...` and Vite forwards
// to the engine. The engine sends no CORS headers on purpose, so the page
// could not read an answer from another port. Set KRIKO_ENGINE to use an
// engine on another address.
const engine = process.env.KRIKO_ENGINE ?? 'http://127.0.0.1:8787'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': { target: engine, changeOrigin: false } },
    // The watcher covers the whole checkout by default, which includes paths
    // written while it runs: a cargo build's object files and the installers
    // under `builds/`. Windows holds those open, so the watcher fails with
    // EBUSY and, after enough of them, exits and takes the dev server with it.
    // Nothing below is a page's source, so none of it is watched.
    watch: {
      ignored: [
        '**/src-tauri/target/**',
        '**/builds/**',
        '**/dist/**',
        '**/node_modules/**',
      ],
    },
  },
})
