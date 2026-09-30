import { render, screen } from "@testing-library/svelte";
import { fireEvent } from "@testing-library/dom";
import { beforeEach, describe, expect, it } from "vitest";
import App from "./App.svelte";
import { stubFetch } from "./lib/stub-fetch";

const EMPTY = {
    "/api/settings": {},
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
        expect(await screen.findByRole("link", { name: "History" })).toBeInTheDocument();
    });

    it("opens on Home, since New check is gone (B163, B174)", async () => {
        stubFetch(EMPTY);
        render(App);
        expect(await screen.findByRole("link", { name: "Home" })).toHaveAttribute(
            "aria-current",
            "page",
        );
        expect(screen.queryByRole("link", { name: "New check" })).toBeNull();
        expect(screen.queryByText("Check one before you buy it")).toBeNull();
    });

    it("lands the old #/check address on Home (B163, B174)", async () => {
        window.location.hash = "#/check";
        stubFetch(EMPTY);
        render(App);
        expect(await screen.findByRole("link", { name: "Home" })).toHaveAttribute(
            "aria-current",
            "page",
        );
        expect(screen.queryByText(/No such view/)).toBeNull();
    });

    it("renders a screen that used to be author-only, with no switch to reach it (B165)", async () => {
        window.location.hash = "#/coverage";
        stubFetch(EMPTY);
        render(App);
        expect(await screen.findByRole("link", { name: "Browse" })).toHaveAttribute(
            "aria-current",
            "page",
        );
        expect(screen.queryByText(/for pack authors/i)).toBeNull();
        expect(screen.queryByRole("button", { name: /switch to author mode/i })).toBeNull();
        expect(screen.queryByRole("group", { name: "Mode" })).toBeNull();
    });

    it("ignores a mode a link or an older install carried (B165)", async () => {
        window.location.hash = "#/about?mode=buyer";
        stubFetch({ ...EMPTY, "/api/settings": { mode: "buyer" } });
        render(App);
        // Knowledge and System are in the rail even though the old setting
        // and the old link both said buyer.
        expect(await screen.findByRole("link", { name: "Agents" })).toBeInTheDocument();
        expect(screen.getByRole("link", { name: "Browse" })).toBeInTheDocument();
        for (const link of document.querySelectorAll("a")) {
            expect(link.getAttribute("href") ?? "").not.toContain("mode=");
        }
    });

    it("lands #/packs on Browse, with the installed packs at its top (B167)", async () => {
        window.location.hash = "#/packs?mode=author";
        stubFetch({
            ...EMPTY,
            "/api/settings": { mode: "author" },
            "/api/packs": [
                { pack_id: "tools", name: "Tools", version: "0.2.0", enabled: true,
                  subjects: 4, claims: 9, evidence: 12, digest: "abc123" },
            ],
            "/api/subjects": [],
            "/api/packs/drafts": { items: [] },
            "/api/packs/tools/gaps": [],
        });
        render(App);
        expect(await screen.findByRole("tab", { name: /What is here/ })).toBeInTheDocument();
        expect(await screen.findByText(/4 subjects · 9 claims/)).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Install pack" })).toBeInTheDocument();
    });

    it("names an unknown route rather than showing a blank workspace", async () => {
        window.location.hash = "#/nonsense";
        stubFetch(EMPTY);
        render(App);
        expect(await screen.findByText(/No such view/)).toBeInTheDocument();
    });

    it("opens the result when the extension hands over the old questions route (B163)", async () => {
        // The panel's "Ask the seller" button posts `questions/<id>` to
        // `/api/focus`. The sheet is gone, and the claim with its ask is on
        // the result, so that route resolves there.
        window.location.hash = "#/questions/L1";
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
        expect(await screen.findByText("T-h")).toBeInTheDocument();
        expect(screen.queryByText(/No such view/)).toBeNull();
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
        expect(await screen.findByRole("link", { name: "History" })).toBeInTheDocument();
        expect(screen.queryByText(/knows nothing yet/)).not.toBeInTheDocument();
    });

    /* B161: "Remove the 'Open coverage' indicator (annoying)". The banner was
     * mounted once here and offered the first unmet step on every screen. What
     * the reader sees now is no suggestion bar at all, however much is unmet:
     * this store has no check run yet and no agent connected, which is exactly
     * what used to raise one. */
    it("shows no next-step banner, even when there is something to suggest", async () => {
        window.location.hash = "#/about";
        stubFetch(EMPTY);
        render(App);
        // The screen has rendered (About's heading), so an absent banner is
        // an absence and not a screen that had not loaded yet.
        expect(await screen.findByRole("heading", { name: /This install/ })).toBeInTheDocument();
        await new Promise((resolve) => setTimeout(resolve, 60));
        expect(screen.queryByRole("complementary", { name: /next step/i })).toBeNull();
        expect(screen.queryByRole("button", { name: /dismiss this suggestion/i })).toBeNull();
        expect(document.querySelector(".nextstep")).toBeNull();
    });

    /* B159: Panel is the only theme. A `theme` row an older install left in the
     * settings table, and the copy of it the old first-paint script mirrored to
     * browser storage, are read by nothing, so neither can repaint the app. */
    it("ignores a theme an older install remembered", async () => {
        localStorage.setItem("kriko-theme", "lemonade");
        stubFetch({ ...EMPTY, "/api/settings": { theme: "lemonade" } });
        render(App);
        expect(await screen.findByRole("link", { name: "History" })).toBeInTheDocument();
        expect(document.documentElement.hasAttribute("data-theme")).toBe(false);
        localStorage.removeItem("kriko-theme");
    });

    it("does not block the app when the status call fails", async () => {
        stubFetch({ ...EMPTY, "/api/status": { status: 500, body: "boom" } });
        render(App);
        expect(await screen.findByRole("link", { name: "History" })).toBeInTheDocument();
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

        window.location.hash = "#/history";
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
