import { render, screen } from "@testing-library/svelte";
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
        expect(await screen.findByText(/author view/i)).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "author" })).toBeInTheDocument();
    });

    it("names an unknown route rather than showing a blank workspace", async () => {
        window.location.hash = "#/nonsense?mode=buyer";
        stubFetch(EMPTY);
        render(App);
        expect(await screen.findByText(/No such view/)).toBeInTheDocument();
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
});
