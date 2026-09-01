/// <reference types="vitest" />
import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vite";

// base is /static/ because FastAPI mounts StaticFiles at /static and serves
// static/index.html from /. outDir is the committed bundle, deliberately
// outside ui/ so the Python wheel ships it without shipping the source.
export default defineConfig(({ mode }) => ({
    plugins: [svelte()],
    base: "/static/",
    build: { outDir: "../src/app/web/static", emptyOutDir: true },
    server: { proxy: { "/api": "http://127.0.0.1:8787" } },
    // Under vitest, resolve svelte's browser build. Without this the plugin
    // hands back the server compilation and every component test dies on
    // `mount(...) is not available on the server` — these are client
    // components and there is no SSR anywhere in this app.
    resolve: mode === "test" ? { conditions: ["browser"] } : {},
    test: {
        environment: "jsdom",
        globals: true,
        setupFiles: ["./src/test-setup.ts"],
    },
}));
