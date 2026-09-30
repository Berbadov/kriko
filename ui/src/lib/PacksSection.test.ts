import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import PacksSection from "./PacksSection.svelte";

const PACK = {
    pack_id: "tools",
    name: "Tools",
    version: "0.2.0",
    enabled: true,
    subjects: 4,
    claims: 9,
    evidence: 12,
    digest: "abc123",
};

describe("PacksSection", () => {
    it("lists an installed pack with its counts", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([PACK]))));
        render(PacksSection);
        expect(await screen.findByText("Tools")).toBeInTheDocument();
        expect(await screen.findByText(/4 subjects · 9 claims/)).toBeInTheDocument();
    });

    it("has no Updates block: it never reads the index and offers no update button", async () => {
        const fetchMock = vi.fn(async (_path: string) => new Response(JSON.stringify([PACK])));
        vi.stubGlobal("fetch", fetchMock);
        render(PacksSection);
        await screen.findByText("Tools");
        expect(screen.queryByRole("button", { name: /Check for updates/ })).toBeNull();
        expect(screen.queryByRole("button", { name: /Update/ })).toBeNull();
        expect(screen.queryByRole("heading", { name: /Updates/ })).toBeNull();
        const asked = fetchMock.mock.calls.map((call) => String(call[0]));
        expect(asked.some((url) => url.startsWith("/api/packs/updates"))).toBe(false);
    });

    it("tells its screen when the catalogs changed, so Browse's own lists follow", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([PACK]))));
        const onchange = vi.fn();
        render(PacksSection, { onchange });
        await screen.findByText("Tools");
        // Loading is not a change.
        expect(onchange).not.toHaveBeenCalled();
        await fireEvent.click(screen.getByRole("button", { name: "Disable Tools" }));
        await waitFor(() => expect(onchange).toHaveBeenCalled());
    });

    it("refuses to install with no file chosen", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => new Response("[]")));
        render(PacksSection);
        await fireEvent.click(await screen.findByRole("button", { name: "Install pack" }));
        expect(await screen.findByText(/Choose a .kpack file first/)).toBeInTheDocument();
    });

    /* A screen with nothing on it is a state, not an absence.
     *
     * This was one grey line reading "No packs installed." — the same fact
     * with the next step left as an exercise, in an app where an empty store
     * means every lookup succeeds and finds nothing. Every other screen-level
     * absence in the app renders the shared EmptyState; this one now does
     * too, which is the whole of the consistency being asked for. */
    it("explains an empty store rather than labelling it", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([]))));
        render(PacksSection);
        expect(await screen.findByText("No catalogs installed")).toBeInTheDocument();
        expect(screen.getByText(/finds nothing/)).toBeInTheDocument();
        expect(document.querySelector(".empty-state")).not.toBeNull();
    });
});
