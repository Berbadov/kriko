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
const BASE = SHEETS["./base.css"];

const COMPONENTS = import.meta.glob("../lib/shell/*.svelte", {
    query: "?raw",
    import: "default",
    eager: true,
}) as Record<string, string>;

/** The declarations inside the first `selector { ... }` block, flattened.
 *  Reads `components.css` unless a different sheet is passed in. */
function block(selector: string, sheet: string = CSS): string {
    const at = sheet.indexOf(`\n${selector} {`);
    expect(at, `no rule for \`${selector}\` — has it been renamed?`).toBeGreaterThan(-1);
    const open = sheet.indexOf("{", at);
    const close = sheet.indexOf("\n}", open);
    return sheet.slice(open + 1, close);
}

/** Same idea, for a rule reached by a multi-selector list (`.a,\n.b {`)
 *  rather than a single selector `block()` can find by its own opening line —
 *  found by any substring unique to the rule's selector list instead. */
function ruleContaining(fragment: string, sheet: string = CSS): string {
    const at = sheet.indexOf(fragment);
    expect(at, `no rule containing \`${fragment}\` — has it been renamed?`).toBeGreaterThan(-1);
    const open = sheet.indexOf("{", at);
    const close = sheet.indexOf("\n}", open);
    return sheet.slice(open + 1, close);
}

describe("shared control styling", () => {
    it("uses the ring as a width and the accent as its colour", () => {
        for (const selector of [".brand:focus-visible"]) {
            expect(block(selector)).toContain("outline: var(--ring) solid var(--accent)");
            expect(block(selector)).toContain("outline-offset: var(--ring)");
        }
        expect(ruleContaining(".nav-link:focus-visible,")).toContain(
            "outline: var(--ring) solid var(--accent)",
        );
    });

    it("uses semantic secondary ink for navigation labels and figures", () => {
        for (const selector of [".nav-link", ".nav-figure", ".nav-title"]) {
            expect(block(selector)).toContain("color: var(--dim)");
        }
    });

    it("pairs compact type with its own leading rather than inherited body leading", () => {
        const css = CSS.replace(/\/\*[\s\S]*?\*\//g, "");
        const rules = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)];
        const compact = rules.filter(([, , body]) => /font-size:\s*var\(--t-(xs|sm)\)/.test(body));
        expect(compact.length).toBeGreaterThan(20);
        for (const [, selector, body] of compact) {
            const size = body.match(/font-size:\s*var\(--t-(xs|sm)\)/)![1];
            expect(body, selector.trim()).toContain(`line-height: var(--lh-${size})`);
        }
    });

    it("spaces shared forms without changing prose asks", () => {
        expect(block("form.ask")).toContain("gap: var(--s-3)");
        expect(block("form.ask")).toContain("display: grid");
        expect(block("form.ask > .field")).toContain("width: 100%");
        expect(block(".ask")).not.toContain("display: grid");
    });
});

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
        expect(reduced).toMatch(/\.nav-slot\s*\{\s*animation:\s*none/);
    });
});

/* The active-row bar used to be a second element Sidebar.svelte positioned in
 * JS from a measured DOM rect (`rowFor(...).offsetTop`, applied after
 * `tick()`). That measurement was only ever retaken on navigation, so it went
 * stale for every reason a row's on-screen position can change *without* a
 * navigation — a fallback font swapping in (`font-display: swap` in
 * fonts.css deliberately does not block first paint), the `(max-height:
 * 820px)` breakpoint changing `.nav-link` padding, `.rail-nav` scrolling on
 * its own. None of those are things jsdom's layout-free renderer can see —
 * which is exactly why the bug survived a full render-test suite — so, as
 * above, this is asserted against the stylesheet and the component source
 * rather than a rendered box.
 *
 * The fix removes the measurement rather than patching it: `.nav-link.active`
 * draws its own bar with `::before`, positioned by the row's own box, so the
 * browser's ordinary layout pass keeps it correct through every case above
 * with nothing left here to go stale.
 */
describe("the active-row indicator", () => {
    it("is a bar the active row draws for itself, not a rect placed by JS", () => {
        const rules = block(".nav-link.active::before");
        expect(rules).toMatch(/position:\s*absolute/);
        expect(rules).toMatch(/background:\s*var\(--accent\)/);
        // `.nav-link` has to be the positioning context, or the bar is
        // absolute against whatever ancestor the cascade hands it instead.
        expect(block(".nav-link")).toMatch(/position:\s*relative/);
    });

    it("has nothing left in Sidebar.svelte to re-measure and go stale", () => {
        const path = Object.keys(COMPONENTS).find((p) => p.endsWith("Sidebar.svelte"));
        expect(path, "Sidebar.svelte not found by the glob").toBeTruthy();
        // Block comments stripped first: this file's own history of the bug
        // names `offsetTop` in prose (see above), and a comment recalling the
        // mechanism is not the mechanism coming back.
        const source = COMPONENTS[path as string].replace(/\/\*[\s\S]*?\*\//g, "");
        // A DOM rect read back into state is exactly the mechanism that
        // shipped stale — if this reappears, so does the whole class of bug
        // the CSS-only bar exists to remove.
        expect(source).not.toMatch(/offsetTop|offsetHeight|getBoundingClientRect/);
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
        // But bare `height: 100vh` still has to land *before* the `dvh`
        // line: it is the fallback for a WebView2 runtime old enough not to
        // parse `dvh` at all, which drops the whole declaration and keeps
        // whichever `height` came before it. Without this, that runtime's
        // `.shell` has no `height` at all — `auto`, sized by its content,
        // and taller than the window is a document-level scrollbar again.
        expect(rules).toMatch(/height:\s*100vh;\s*\n\s*height:\s*100dvh/);
        // The belt: nothing outside the two scrollers may ever scroll.
        expect(rules).toMatch(/overflow:\s*clip/);
    });

    it("cannot show a document scrollbar even if .shell's own height is a hair off", () => {
        // `.shell` clips its own overflow; it says nothing about `html` or
        // `body`. A `dvh` that is a fraction of a device pixel taller than
        // the true client area — plausible from nothing but a display's DPI
        // scaling — is invisible to `.shell`'s own rule and shows up as the
        // OS's own scrollbar around the whole window unless the document
        // itself is also told it may not scroll.
        expect(BASE?.length ?? 0).toBeGreaterThan(50);
        const html = block("html", BASE);
        const body = block("body", BASE);
        expect(html).toMatch(/overflow:\s*hidden/);
        expect(body).toMatch(/overflow:\s*hidden/);
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

    it("gives the work column the design system's own scrollbar, not the OS's", () => {
        // Both property forms are required, not either: `scrollbar-color` is
        // what a modern engine reads, `::-webkit-scrollbar-thumb` is what a
        // Chromium old enough not to support that property reads instead —
        // and a WebView2 runtime behind on updates is exactly that engine.
        // Leaving either one out means the "Windows 95" bar is still one
        // engine version away from coming back.
        const rules = ruleContaining(".work,\n.log,\n.table-scroll {");
        expect(rules).toMatch(/scrollbar-width:\s*thin/);
        expect(rules).toMatch(/scrollbar-color:\s*var\(--line\)/);
        const thumb = ruleContaining(".work::-webkit-scrollbar-thumb,");
        expect(thumb).toMatch(/background:\s*var\(--line\)/);
    });

    it("never lets an unbroken long string push the layout wider than the window", () => {
        // Inherited, so this is one declaration for every card, title and raw
        // URL in the app rather than a per-component fix repeated twenty times.
        // `break-word` (not `anywhere`): `anywhere` also shrinks every
        // flex/table child's min-content width to one character, which is
        // what let button labels, tab labels and table headers split
        // mid-word once their box got tight (B145 shell-3/uicode-m1).
        // `break-word` still breaks a URL with nowhere else to go.
        expect(block("body", BASE)).toMatch(/overflow-wrap:\s*break-word/);
    });

    it("does not style a radio as if it were a text field", () => {
        /* `min-width: 150px` on a bare `input` selector gave every radio and
         * checkbox a 150px-wide box with the glyph at its left edge — in
         * Settings the dot sat ~100px from the label it belonged to. The
         * text-field rule must name text fields. */
        const field = block(
            'input:not([type="radio"]):not([type="checkbox"]),\nselect,\ntextarea',
        );
        expect(field).toMatch(/min-width:\s*150px/);

        // And the toggles get their own rule, sized intrinsically.
        const toggle = block('input[type="radio"],\ninput[type="checkbox"]');
        expect(toggle).not.toMatch(/min-width/);
        // The app's gold, not the operating system's blue.
        expect(toggle).toMatch(/accent-color:\s*var\(--accent\)/);
    });

    /* B160: "Make all buttons and selections 3D, button-like". Held against the
     * declarations because jsdom draws nothing: what can be asserted is that
     * every control spends the button's own tokens, so that a change to the
     * button's face moves them together and none can drift back to flat. */
    describe("the raised control kit", () => {
        const FACE = [
            /background-color:\s*var\(--btn\)/,
            /border-top-color:\s*var\(--btn-hi\)/,
            /border-bottom-color:\s*var\(--btn-lo\)/,
            /box-shadow:\s*var\(--shadow-1\)/,
        ];
        const PRESS = [
            /transform:\s*translateY\(var\(--lift\)\)/,
            /box-shadow:\s*none/,
            /background-color:\s*var\(--btn-active\)/,
        ];

        it("gives text fields, selects and text areas the button's face", () => {
            const field = block(
                'input:not([type="radio"]):not([type="checkbox"]),\nselect,\ntextarea',
            );
            for (const part of FACE) expect(field).toMatch(part);
        });

        it("presses a field one pixel, exactly as a button sinks", () => {
            const press = ruleContaining(
                'input:not([type="radio"]):not([type="checkbox"]):active:not(:disabled),',
            );
            for (const part of PRESS) expect(press).toMatch(part);
            const hover = ruleContaining(
                'input:not([type="radio"]):not([type="checkbox"]):hover:not(:disabled),',
            );
            expect(hover).toMatch(/background-color:\s*var\(--btn-hover\)/);
            expect(hover).toMatch(/border-color:\s*var\(--accent\)/);
            // A disabled field must stop looking pressable, as a button does.
            expect(ruleContaining("input:disabled,\nselect:disabled,")).toMatch(/transform:\s*none/);
        });

        it("draws one arrow on a select, from tokens, and leaves it a native select", () => {
            const select = block("select");
            expect(select).toMatch(/appearance:\s*none/);
            // The arrow is gradients over the dim ink, not a data-URI stroke: a
            // literal colour there is what tokens.test.ts refuses.
            expect(select).toMatch(/linear-gradient\([^)]*var\(--dim\)/);
            // The hover keeps it, so `background-color` (not the shorthand,
            // which would reset the image) is what a hover changes.
            expect(ruleContaining("select:hover:not(:disabled) {")).toMatch(
                /linear-gradient\([^)]*var\(--accent\)/,
            );
            // Native semantics stay: no listbox replacement is in the sheet.
            expect(CSS).not.toMatch(/role="listbox"/);
        });

        it("draws a radio choice as a raised card with a press of its own", () => {
            const card = block(".choice");
            for (const part of FACE) expect(card).toMatch(part);
            for (const part of PRESS) expect(block(".choice:active")).toMatch(part);
            // Chosen is a fill and an edge, not only a border hue.
            expect(block(".choice.on")).toMatch(/background-color:\s*var\(--accent-soft\)/);
            expect(block(".choice.on")).toMatch(/border-color:\s*var\(--accent\)/);
        });

        it("never draws the native file control", () => {
            // The real input is kept and hidden; a button on the button face
            // takes its place (lib/FilePick.svelte).
            expect(block(".file-pick input[type=\"file\"]")).toMatch(/display:\s*none/);
        });

        it("gives a link drawn as a button its press too", () => {
            for (const part of PRESS.slice(0, 2)) expect(block(".button-like:active")).toMatch(part);
        });
    });

    it("draws the rail's mark as a smooth vector, never a pixelated bitmap", () => {
        // B161: "Fix the pixelated Kriko logo in the top left". The mark began
        // as a 16-cell grid drawn at 28px with `image-rendering: pixelated`, a
        // 1.75 scale that no smoothing setting makes crisp. The rebuild goes
        // further: the rail now carries the design system's own wordmark SVG
        // (kriko-svelte/assets), white on the blue brand plate, so the old
        // 32px square and its fixed width are gone with the bitmap. What must
        // never come back is a raster mark scaled by the browser.
        const mark = block(".brand .mark").replace(/\/\*[\s\S]*?\*\//g, "");
        expect(mark).not.toMatch(/image-rendering/);
        // The vector keeps its own aspect: height is drawn, width follows it.
        expect(mark).toMatch(/height:\s*20px/);
        expect(mark).toMatch(/width:\s*auto/);
    });

    it("does not draw a focus ring around the whole screen", () => {
        /* `.view` takes focus programmatically on every route change so a
         * screen reader starts at the new screen. Chrome matches
         * `:focus-visible` on a programmatic focus, so the universal focus rule
         * painted a 2px accent rectangle around the entire content column — on
         * every screen, from the first navigation onward. It was the largest
         * and brightest element in the app and nobody had asked for it.
         *
         * jsdom computes no focus ring and renders no box, so only the
         * declaration can be held to account — the same trade the header
         * explains. */
        expect(block(".view:focus,\n.view:focus-visible", BASE)).toMatch(
            /outline:\s*none/,
        );
        // And the rule it overrides is still there: suppressing the container's
        // ring must not have been done by deleting everyone else's.
        expect(block(":focus-visible", BASE)).toMatch(/outline:.*var\(--accent\)/);
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
