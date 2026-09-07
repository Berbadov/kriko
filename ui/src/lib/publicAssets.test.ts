import { describe, expect, it } from "vitest";

// Vite's own glob, for the same reason tokens.test.ts uses it: this tsconfig
// ships no Node types.
const SOURCES = import.meta.glob("../**/*.svelte", {
    query: "?raw",
    import: "default",
    eager: true,
}) as Record<string, string>;

// The bug this exists for shipped in 0.3.2 and was visible on every screen:
// the rail's mark was `src="/mark.svg"`. Vite's `base` is `/static/` because
// FastAPI mounts StaticFiles at `/static`, so a root-relative path to a
// `public/` asset does not reach the file — it falls through to the SPA
// catch-all, which answers with index.html, and the browser renders a broken
// image with no error anywhere. Nothing in the type system or the build can
// notice: both spellings are valid HTML and both build cleanly.
//
// Anything genuinely served from the root — the API — is exempt: `/api/...`
// is a route on the server, not a bundled asset.
const ROOT_HREF = /\b(?:src|href)=["'](\/(?!static\/|api\/)[^"']*)["']/g;

describe("public assets are referenced through Vite's base", () => {
    it("no component points at a root-relative asset", () => {
        const offenders: string[] = [];
        for (const [path, source] of Object.entries(SOURCES)) {
            for (const match of source.matchAll(ROOT_HREF)) {
                offenders.push(`${path}: ${match[1]}`);
            }
        }
        expect(offenders).toEqual([]);
    });
});
