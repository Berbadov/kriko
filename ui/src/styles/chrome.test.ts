/* Application chrome must not scroll like a document.
 *
 * The gate that did not exist. `.rail` was `height: 100vh` with
 * `overflow-y: auto`, so at any window short enough to clip the nav, the
 * brand mark and the mode switch scrolled away with it and a web-page
 * scrollbar ran down the side of the navigation. `svelte-check` passed,
 * every render test passed, and nothing in the suite could see it — layout
 * is exactly what jsdom does not do.
 *
 * So this is asserted against the stylesheet rather than a rendered box.
 * That is not a compromise: the rule *is* a rule about the declarations. A
 * jsdom render could not have caught this at any effort, and a real browser
 * harness for one CSS property is not the trade.
 */
import { describe, expect, it } from "vitest";

const SHEETS = import.meta.glob("./**/*.css", {
    query: "?raw",
    import: "default",
    eager: true,
}) as Record<string, string>;

const CSS = SHEETS["./components.css"];

/** The declarations inside the first `selector { ... }` block, flattened. */
function block(selector: string): string {
    const at = CSS.indexOf(`\n${selector} {`);
    expect(at, `no rule for \`${selector}\` — has it been renamed?`).toBeGreaterThan(-1);
    const open = CSS.indexOf("{", at);
    const close = CSS.indexOf("\n}", open);
    return CSS.slice(open + 1, close);
}

describe("the rail", () => {
    it("is actually reading the sheet", () => {
        expect(CSS?.length ?? 0).toBeGreaterThan(200);
    });

    it("does not scroll — the whole rail is chrome", () => {
        const rules = block(".rail");
        expect(rules).toMatch(/overflow:\s*clip/);
        expect(rules).not.toMatch(/overflow-y:\s*(auto|scroll)/);
        expect(rules).not.toMatch(/overflow:\s*(auto|scroll)/);
    });

    it("gives the nav a shrinkable track, not a 1fr one", () => {
        // `1fr` alone is `minmax(auto, 1fr)`, and a grid track's automatic
        // minimum is its content — so the nav would refuse to shrink and push
        // the overflow straight back out to the rail. This one `minmax(0, ...)`
        // is what makes the fix work at all.
        expect(block(".rail")).toMatch(/grid-template-rows:\s*auto\s+minmax\(0,\s*1fr\)\s+auto/);
    });

    it("scrolls the nav rows, and only the nav rows", () => {
        const rules = block(".rail-nav");
        expect(rules).toMatch(/overflow-y:\s*auto/);
        // Without this the track's minimum is its content again, one level in.
        expect(rules).toMatch(/min-height:\s*0/);
        // The bar itself was the complaint. Overflow is conveyed by the
        // scroll-shadow gradients instead.
        expect(rules).toMatch(/scrollbar-width:\s*none/);
        expect(rules).toMatch(/background-attachment:\s*local/);
    });

    it("leaves the rail's motion out under reduced motion", () => {
        const at = CSS.indexOf("prefers-reduced-motion");
        expect(at).toBeGreaterThan(-1);
        const reduced = CSS.slice(at);
        expect(reduced).toMatch(/\.nav-mark\s*\{\s*transition:\s*none/);
        expect(reduced).toMatch(/\.nav-slot\s*\{\s*animation:\s*none/);
    });
});
