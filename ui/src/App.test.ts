import { render, screen } from "@testing-library/svelte";
import { fireEvent } from "@testing-library/dom";
import { beforeEach, describe, expect, it } from "vitest";
import App from "./App.svelte";
import { stubFetch } from "./lib/stub-fetch";

const EMPTY = {
    "/api/settings": { mode: "buyer" },
    "/api/status": { ok: true, packs: 1, enabled_packs: 1, counts: {} },
    "/api/packs": [],
    "/api/adapters": [],
    "/api/history": { items: [] },
};

describe("App", () => {
    beforeEach(() => {
        window.location.hash = "";
    });

    it("renders the rail beside the workspace", async () => {
        stubFetch(EMPTY);
        render(App);
        expect(await screen.findByRole("link", { name: "New check" })).toBeInTheDocument();
    });

    it("explains an author route to a buyer instead of rendering nothing", async () => {
        window.location.hash = "#/coverage?mode=buyer";
        stubFetch(EMPTY);
        render(App);
        expect(await screen.findByText(/for pack authors/i)).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "author" })).toBeInTheDocument();
        expect(
            screen.getByRole("button", { name: "Switch to author mode" }),
        ).toBeInTheDocument();
    });

    it("names an unknown route rather than showing a blank workspace", async () => {
        window.location.hash = "#/nonsense?mode=buyer";
        stubFetch(EMPTY);
        render(App);
        expect(await screen.findByText(/No such view/)).toBeInTheDocument();
    });

    it("opens the question sheet from a path the extension can hand over", async () => {
        // The panel's "Ask the seller" button posts a route to `/api/focus`,
        // which refuses a query string on purpose — so the id can only travel
        // as a path segment. The rail's own entry (`#/questions`, no id) and
        // the report's link (`?id=`) both still work; this is a third
        // spelling of the same screen, added for the one caller that cannot
        // use the other two.
        window.location.hash = "#/questions/L1?mode=buyer";
        stubFetch({
            ...EMPTY,
            "/api/history": {
                items: [{
                    lookup_id: "L1", created_at: "2026-09-01", source: "url",
                    label: "The one", claim_count: 1,
                }],
            },
            "/api/lookup/L1": {
                lookup_id: "L1", created_at: "", source: "url",
                label: "The one", request: {},
                response: { method: "exact", claims: [{
                    claim_id: "h", title: "T-h", body: "b",
                    advice: "Ask for the receipt.", severity: "high",
                    subject: "s", relevance: 0.5, pack_id: "p",
                }] },
            },
            "/api/lookups/L1/triage": { checked: [], notes: {} },
        });
        render(App);
        expect(
            await screen.findByText("Ask for the receipt."),
        ).toBeInTheDocument();
    });

    it("shows first run when the store is empty", async () => {
        stubFetch({
            ...EMPTY,
            "/api/status": { ok: true, packs: 0, enabled_packs: 0, counts: {} },
            "/api/packs/updates": { index_url: "u", error: null, packs: [] },
        });
        render(App);
        expect(await screen.findByText(/knows nothing yet/)).toBeInTheDocument();
    });

    it("does not show first run once a pack is installed", async () => {
        stubFetch(EMPTY);
        render(App);
        expect(await screen.findByRole("link", { name: "New check" })).toBeInTheDocument();
        expect(screen.queryByText(/knows nothing yet/)).not.toBeInTheDocument();
    });

    it("does not block the app when the status call fails", async () => {
        stubFetch({ ...EMPTY, "/api/status": { status: 500, body: "boom" } });
        render(App);
        expect(await screen.findByRole("link", { name: "New check" })).toBeInTheDocument();
        expect(screen.queryByText(/knows nothing yet/)).not.toBeInTheDocument();
    });

    /* The shell's half of navigation.
     *
     * A hash router replaces the contents of one document: no load event, so
     * nothing is announced, and focus stays wherever it was — in the rail,
     * groups above whatever just appeared. Both of those are the browser's
     * job going unclaimed, and neither is visible in a screenshot. */
    it("puts a skip control first, and moves focus into the view", async () => {
        stubFetch(EMPTY);
        render(App);
        const skip = await screen.findByRole("button", { name: "Skip to content" });
        // First in the tab order: it is the first control in the document, not
        // merely present somewhere.
        const controls = document.querySelectorAll("button, a[href], input, select");
        expect(controls[0]).toBe(skip);

        await fireEvent.click(skip);
        const view = document.querySelector(".view") as HTMLElement;
        expect(view.getAttribute("tabindex")).toBe("-1");
        expect(document.activeElement).toBe(view);
    });

    it("announces the screen it navigated to, and not the one it loaded on", async () => {
        stubFetch(EMPTY);
        render(App);
        const live = await screen.findByRole("status");
        // Load is not a navigation: announcing here would talk over a reader
        // who has not heard the rail yet, and focus would be stolen from the
        // top of the document.
        expect(live.textContent?.trim()).toBe("");

        window.location.hash = "#/history?mode=buyer";
        await fireEvent(window, new HashChangeEvent("hashchange"));
        expect((await screen.findByRole("status")).textContent).toContain("History");
        expect(document.activeElement).toBe(document.querySelector(".view"));
    });

    it("carries the live region outside the keyed subtree", async () => {
        // A live region that is itself replaced on navigation announces
        // nothing: the text and the element carrying it arrive in the same
        // paint, so there is no change for the reader to be told about.
        stubFetch(EMPTY);
        render(App);
        const live = await screen.findByRole("status");
        expect(live.closest(".enter")).toBeNull();
        expect(live.getAttribute("aria-live")).toBe("polite");
    });
});
