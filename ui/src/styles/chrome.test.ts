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

/* The other half of the same rule, and the half that shipped broken.
 *
 * The rail was taught not to scroll like a document; the work column never
 * was. `.shell` was `min-height: 100vh` with a `100vh` sticky rail, so the
 * *document* grew past the viewport and the browser ran its own scrollbar
 * down the right-hand edge of the window — the one piece of visible browser
 * chrome in an app that is otherwise a window, and the first thing a reader
 * notices is wrong about it.
 *
 * Asserted against the declarations for the same reason as the rules above:
 * jsdom has no layout, so a render test cannot see a scrollbar at any effort.
 */
describe("the work column", () => {
    it("gives the shell a viewport-sized frame, not a minimum", () => {
        const rules = block(".shell");
        // `dvh`, not `vh`: on a phone or a narrow window with a retracting
        // toolbar, `100vh` is taller than what you can see, which is the
        // same scrollbar again by another route.
        expect(rules).toMatch(/height:\s*100dvh/);
        expect(rules).not.toMatch(/min-height:\s*100vh/);
        // The belt: nothing outside the two scrollers may ever scroll.
        expect(rules).toMatch(/overflow:\s*clip/);
    });

    it("scrolls the work column itself", () => {
        const rules = block(".work");
        expect(rules).toMatch(/overflow-y:\s*auto/);
        // A grid track's automatic minimum is its content — without this the
        // column refuses to shrink and pushes the overflow back out to the
        // document, which is the bug being fixed.
        expect(rules).toMatch(/min-height:\s*0/);
        // Reserved, so arriving at a long page does not shove the whole
        // layout 15px left. The gutter is the fix for the jump; hiding the
        // bar is not, because this is content and content may scroll.
        expect(rules).toMatch(/scrollbar-gutter:\s*stable/);
    });

    it("keeps the scrollbar at the window edge, not mid-page", () => {
        // The 1100px cap moved off the scroller and onto the content: a
        // scroller capped at 1100px paints its bar at 1100px, which on a wide
        // window is a scrollbar floating in the middle of the screen.
        expect(block(".work")).not.toMatch(/max-width:\s*1100px/);
        expect(block(".view")).toMatch(/max-width:\s*1100px/);
    });

    it("undoes both scrollers on paper", () => {
        // A fixed-height clipping frame prints as one page of a ten-page
        // report. The screen rules and the print rules are one change.
        const PRINT = SHEETS["./print.css"];
        expect(PRINT?.length ?? 0).toBeGreaterThan(200);
        const at = PRINT.indexOf("@media print");
        const printed = PRINT.slice(at);
        expect(printed).toMatch(/\.shell\s*\{[^}]*height:\s*auto/);
        expect(printed).toMatch(/\.shell\s*\{[^}]*overflow:\s*visible/);
        expect(printed).toMatch(/\.work\s*\{[^}]*overflow:\s*visible/);
    });
});
