/* Every screen in the rail, walked with a keyboard.
 *
 * B74. The suite tested routes one at a time, each with its own hand-written
 * hash — so what nothing checked was the *walk*: start at the skip control,
 * tab into the rail, and land on a real screen at every stop. Three ways that
 * breaks and none of them failed a test:
 *
 *   1. A rail entry whose name `App.svelte`'s if-chain does not handle renders
 *      "No such view". The link is there, focusable, announced — and there is
 *      no path to that screen at all, by keyboard or mouse.
 *   2. A screen that renders but whose route is not in `NAV` is reachable only
 *      by typing a URL, which in a desktop app with no address bar means it is
 *      not reachable.
 *   3. Focus escaping a modal into a document behind a scrim: the reader is
 *      focused on something they cannot see, with no key that gets them back.
 *
 * Driven off `NAV` rather than a list here, so a screen added tomorrow is
 * covered the day it appears — a hand-written route list in a test is the same
 * bug as a hand-written route list in the palette.
 */
import { render, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";

import App from "./App.svelte";
import { ALL_ROUTES, NAV, labelOf } from "./lib/shell/nav";
import { stubFetch } from "./lib/stub-fetch";

// Every rail entry exists for everyone (B165), so the walk covers all of them.
const ROUTES = {
    "/api/settings": {},
    "/api/status": { ok: true, packs: 1, enabled_packs: 1, counts: {} },
    "/api/packs": [],
    "/api/adapters": [],
    "/api/adapters/unmapped": { labels: [] },
    "/api/history": { items: [] },
    "/api/health": { ok: true, version: "test", packs: [] },
    "/api/focus": { route: null },
};

/** Every element a Tab key can reach, in the order Tab reaches them.
 *
 * Document order with negative tabindex removed. That is the whole of the
 * real algorithm here because nothing in this app uses a positive tabindex —
 * which is itself asserted below, since the day something does, this helper
 * quietly stops describing the tab order.
 */
function tabbables(root: ParentNode): HTMLElement[] {
    const selector = [
        "a[href]",
        "button:not([disabled])",
        "input:not([disabled])",
        "select:not([disabled])",
        "textarea:not([disabled])",
        "[tabindex]",
    ].join(",");
    return [...root.querySelectorAll<HTMLElement>(selector)].filter(
        (el) =>
            el.getAttribute("tabindex") !== "-1"
            && !el.closest("[aria-hidden='true']")
            && !el.hasAttribute("hidden"),
    );
}

describe("walking the app with a keyboard", () => {
    beforeEach(() => {
        window.location.hash = "";
    });

    it("meets the skip control before anything else", async () => {
        stubFetch(ROUTES);
        const { container } = render(App);
        await screen.findByRole("link", { name: "History" });
        // First in the tab order, and it is a real control rather than an
        // `<a href="#main">` — the app is hash-routed, so a fragment is an
        // address and `#main` would navigate to "No such view".
        expect(tabbables(container)[0]?.textContent).toContain("Skip to content");
    });

    it("puts no element ahead of document order", async () => {
        // A positive tabindex is how a keyboard walk stops matching what the
        // reader sees, and it is also what would invalidate `tabbables` above.
        stubFetch(ROUTES);
        const { container } = render(App);
        await screen.findByRole("link", { name: "History" });
        for (const el of container.querySelectorAll("[tabindex]")) {
            expect(Number(el.getAttribute("tabindex"))).toBeLessThanOrEqual(0);
        }
    });

    it("offers every rail destination as a focusable link", async () => {
        stubFetch(ROUTES);
        const { container } = render(App);
        await screen.findByRole("link", { name: "History" });
        const reachable = new Set(
            tabbables(container)
                .filter((el) => el.tagName === "A")
                .map((el) => el.textContent?.trim()),
        );
        for (const name of ALL_ROUTES) {
            expect(reachable, `${name} has no focusable rail link`).toContain(
                labelOf(name),
            );
        }
    });
});

describe("every rail destination is a screen", () => {
    beforeEach(() => {
        window.location.hash = "";
    });

    // One case per destination rather than a loop inside one case: a loop
    // reports the first broken screen and hides the rest, and "which screens
    // are missing" is the useful answer.
    for (const group of NAV) {
        for (const item of group.items) {
            it(`${group.title} › ${item.label} renders something`, async () => {
                window.location.hash = `#/${item.name}`;
                stubFetch(ROUTES);
                render(App);
                // Waiting for the *positive* signal first, and this is not a
                // nicety: `waitFor` retries until an assertion passes, so a
                // negative one wrapped in it passes on the empty first frame
                // and the test never sees the screen it is judging. Found by
                // deleting a route from the if-chain and watching this file
                // stay green.
                await waitFor(() => expect(screen.queryByText("Starting…")).toBeNull());
                // The two ways a rail link lands nowhere. Both render a
                // perfectly composed screen, which is why neither shows up in
                // a render test that only asserts "something appeared".
                expect(screen.queryByText(/No such view/)).toBeNull();
                expect(screen.queryByText(/for pack authors/)).toBeNull();
            });
        }
    }
});

/* The next dialog, not this one.
 *
 * The palette's trap is now tested by Palette.test.ts. This is the rule, and
 * it exists because the palette is the app's *first* modal: the second one
 * will be written by someone reading the first, and `aria-modal="true"` is
 * three attributes' worth of copy-paste that carries an obligation with it.
 */
const COMPONENTS = import.meta.glob("./**/*.svelte", {
    query: "?raw",
    import: "default",
    eager: true,
}) as Record<string, string>;

describe("a dialog that says it is modal", () => {
    it("is scanning something", () => {
        expect(Object.keys(COMPONENTS).length).toBeGreaterThan(20);
    });

    it("holds the tab order, in every component that claims to be one", () => {
        const claiming = Object.entries(COMPONENTS).filter(([, source]) =>
            /aria-modal=["{]/.test(source),
        );
        // Not "at least one": the day this finds none, `aria-modal` has been
        // renamed or the palette deleted, and an assertion over an empty list
        // is the shape of a gate that stopped gating.
        expect(claiming.length).toBeGreaterThan(0);
        for (const [path, source] of claiming) {
            expect(source, `${path} is aria-modal but never handles Tab`).toMatch(
                /["']Tab["']/,
            );
        }
    });
});
