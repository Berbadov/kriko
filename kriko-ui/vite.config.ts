import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the page asks its own origin for `/api/...` and Vite forwards
// to the engine. The engine sends no CORS headers on purpose, so the page
// could not read an answer from another port. Set KRIKO_ENGINE to use an
// engine on another address.
const engine = process.env.KRIKO_ENGINE ?? 'http://127.0.0.1:8787'

/** Vendor groups for the production build, so the first paint ships only what the
 *  Ask screen needs. React and the animation library are shared by every screen;
 *  the Markdown pipeline is only needed once an answer is on the screen, so it is
 *  its own chunk, fetched when the conversation view (or the idle prefetch) asks. */
export default defineConfig({
  plugins: [react()],
  build: {
    rolldownOptions: {
      output: {
        // Vite 8 builds with Rolldown: `codeSplitting.groups` replaces Rollup's `manualChunks`.
        codeSplitting: {
          groups: [
            { name: 'vendor-react', test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/, priority: 30 },
            { name: 'vendor-motion', test: /node_modules[\\/](motion|motion-dom|motion-utils|framer-motion)[\\/]/, priority: 20 },
            {
              name: 'vendor-markdown',
              test: /node_modules[\\/](react-markdown|remark-[^\\/]+|rehype-[^\\/]+|unified|mdast-[^\\/]+|micromark[^\\/]*|hast-[^\\/]+|unist-[^\\/]+|vfile[^\\/]*|bail|trough|devlop|decode-named-character-reference|character-entities[^\\/]*|property-information|space-separated-tokens|comma-separated-tokens|html-url-attributes|ccount|markdown-table|zwitch|longest-streak|trim-lines|is-plain-obj|style-to-js|style-to-object|inline-style-parser|estree-util-is-identifier-name)[\\/]/,
              priority: 10,
            },
          ],
        },
      },
    },
  },
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
