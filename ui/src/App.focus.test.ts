/* Where focus lands after navigation.
 *
 * The gate that did not exist. `App.svelte`'s navigation effect called
 * `viewEl.focus()` unconditionally, which stole focus from the Console's
 * autofocused prompt and made the console a screen you could not type into.
 * Every one of the 263 tests in this suite passed with that in place, because
 * not one of them asserted where focus goes — so a working command dispatcher
 * behind an unusable input read, from the outside, as "the console is broken".
 *
 * The Console is gone — it was folded into Agents
 * replaced it, mounted outside `.view` and so structurally unable to hit this
 * bug — which leaves no route in the app that currently claims `[autofocus]`.
 * What is asserted below is the mechanism's fallback behaviour, still real
 * and still load-bearing for the next route that autofocuses a control.
 */
import { render, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";
import App from "./App.svelte";
import { stubFetch } from "./lib/stub-fetch";

const ROUTES = {
    "/api/settings": { mode: "author" },
    "/api/status": { ok: true, packs: 1, enabled_packs: 1, counts: {} },
    "/api/packs": [],
    "/api/adapters": [],
    "/api/history": { items: [] },
    "/api/health": { ok: true, version: "test", packs: [] },
    "/api/focus": { route: null },
};

/** Navigate the hash router the way a click on the rail does. */
async function go(hash: string) {
    window.location.hash = hash;
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    await waitFor(() => expect(window.location.hash).toContain(hash.slice(1)));
}

describe("focus after navigation", () => {
    beforeEach(() => {
        window.location.hash = "";
    });

    it("still puts focus on the view container for a route with no autofocus", async () => {
        stubFetch(ROUTES);
        const { container } = render(App);
        await screen.findByRole("link", { name: "New check" });

        await go("#/about?mode=author");

        const view = container.querySelector<HTMLElement>(".view");
        await waitFor(() => expect(document.activeElement).toBe(view));
    });

    it("does not steal focus into the view on first paint", async () => {
        stubFetch(ROUTES);
        const { container } = render(App);
        await screen.findByRole("link", { name: "New check" });
        const view = container.querySelector<HTMLElement>(".view");
        expect(document.activeElement).not.toBe(view);
    });
});
