import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import { stubFetch } from "../lib/stub-fetch";
import Welcome from "./Welcome.svelte";

const OFFERED = {
    "/api/packs/updates": {
        index_url: "https://example.invalid/packs.json",
        error: null,
        packs: [
            { pack_id: "p1", name: "Pack One", installed_version: "", offered_version: "1.0", state: "not_installed", reason: "" },
        ],
    },
};

describe("Welcome", () => {
    it("names what it would install, and where from", async () => {
        stubFetch(OFFERED);
        render(Welcome, { onDone: () => {} });
        expect(await screen.findByText("Pack One")).toBeInTheDocument();
        expect(screen.getByText(/example.invalid/)).toBeInTheDocument();
    });

    it("offers the file path when the index cannot be reached", async () => {
        stubFetch({
            "/api/packs/updates": { index_url: "u", error: "getaddrinfo failed", packs: [] },
        });
        render(Welcome, { onDone: () => {} });
        expect(await screen.findByText(/could not be reached/i)).toBeInTheDocument();
        expect(screen.getByLabelText(/\.kpack file/i)).toBeInTheDocument();
    });

    it("lets the reader past without installing anything", async () => {
        const onDone = vi.fn();
        stubFetch(OFFERED);
        render(Welcome, { onDone });
        await fireEvent.click(await screen.findByRole("button", { name: /Skip/ }));
        expect(onDone).toHaveBeenCalled();
    });

    it("says what an empty store means rather than looking broken", async () => {
        stubFetch({ "/api/packs/updates": { index_url: "u", error: null, packs: [] } });
        render(Welcome, { onDone: () => {} });
        expect(await screen.findByText(/offers no packs/i)).toBeInTheDocument();
    });
});
