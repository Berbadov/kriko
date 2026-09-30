import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Knowledge from "./Knowledge.svelte";
import { stubFetch } from "../lib/stub-fetch";

const STATUS = {
    enabled_packs: 1,
    counts: { packs: 1, subjects: 2, claims: 3, evidence: 4 },
};

const PACK = {
    pack_id: "org.kriko.cars",
    name: "Used cars",
    version: "1.0.0",
    enabled: true,
    subjects: 2,
    claims: 3,
    evidence: 4,
    digest: "abc123",
};

function serve(over: Record<string, unknown> = {}) {
    return stubFetch({
        "/api/status": STATUS,
        "/api/packs": [PACK],
        "/api/subjects": [],
        "/api/packs/org.kriko.cars/gaps": [],
        ...over,
    });
}

describe("Knowledge", () => {
    beforeEach(() => vi.restoreAllMocks());

    it("shows counts before content, so arriving is orientation not a table dump", async () => {
        serve();
        render(Knowledge, {});
        await waitFor(() => expect(screen.getByText("subjects")).toBeInTheDocument());
        expect(screen.getByText("claims")).toBeInTheDocument();
    });

    it("shows three lenses, and no tab for what readers said (B166)", async () => {
        serve();
        render(Knowledge, {});
        await screen.findByRole("tab", { name: /What is here/ });
        expect(screen.getAllByRole("tab").map((tab) => tab.textContent?.trim())).toEqual([
            "What is here",
            "What is missing",
            "What is thin",
        ]);
        expect(screen.queryByText(/What readers said/)).toBeNull();
        expect(screen.queryByText(/Worth researching again/)).toBeNull();
    });

    it("opens on the lens the route named, and an old marks bookmark lands on the first", async () => {
        serve();
        const first = render(Knowledge, { lens: "gaps" });
        await waitFor(() =>
            expect(screen.getByRole("tab", { name: /What is missing/ })).toHaveAttribute(
                "aria-selected",
                "true",
            ),
        );
        first.unmount();
        // `#/marks` resolves to "all" in nav.ts, but a stale `lens=marked`
        // must not leave the screen with no tab selected either.
        render(Knowledge, { lens: "marked" });
        await waitFor(() =>
            expect(screen.getByRole("tab", { name: /What is here/ })).toHaveAttribute(
                "aria-selected",
                "true",
            ),
        );
    });

    it("never asks for the marks any more: the extension posts them, this screen does not read them", async () => {
        serve();
        render(Knowledge, {});
        await screen.findByRole("tab", { name: /What is here/ });
        const asked = vi.mocked(globalThis.fetch).mock.calls.map(([url]) => String(url));
        expect(asked.some((url) => url.startsWith("/api/marks"))).toBe(false);
    });

    it("moves the lens with arrow keys, the same roving-tabindex contract Activity's tabs carry (knowledge-28)", async () => {
        serve();
        render(Knowledge, {});
        const all = await screen.findByRole("tab", { name: /What is here/ });
        expect(all).toHaveAttribute("tabindex", "0");
        const gaps = screen.getByRole("tab", { name: /What is missing/ });
        expect(gaps).toHaveAttribute("tabindex", "-1");
        await fireEvent.keyDown(all, { key: "ArrowRight" });
        expect(gaps).toHaveAttribute("aria-selected", "true");
        expect(gaps).toHaveAttribute("tabindex", "0");
        expect(gaps).toHaveFocus();
        const thin = screen.getByRole("tab", { name: /What is thin/ });
        await fireEvent.keyDown(gaps, { key: "End" });
        expect(thin).toHaveAttribute("aria-selected", "true");
        expect(thin).toHaveFocus();
    });

    it("puts the installed packs at the top, above the lenses, with the install form", async () => {
        serve();
        render(Knowledge, {});
        const heading = await screen.findByRole("heading", { name: /Catalogs/ });
        const tabs = screen.getByRole("tablist");
        // The section comes first in the page, the lenses after it.
        expect(
            heading.compareDocumentPosition(tabs) & Node.DOCUMENT_POSITION_FOLLOWING,
        ).toBeTruthy();
        expect(await screen.findByText("Used cars")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Install pack" })).toBeInTheDocument();
    });

    it("has no Updates block: no check button, no Update all, no index table", async () => {
        serve();
        render(Knowledge, {});
        await screen.findByText("Used cars");
        expect(screen.queryByRole("button", { name: /Check for updates/ })).toBeNull();
        expect(screen.queryByRole("button", { name: /Update all/ })).toBeNull();
        expect(screen.queryByRole("heading", { name: /Updates/ })).toBeNull();
        const asked = vi.mocked(globalThis.fetch).mock.calls.map(([url]) => String(url));
        expect(asked.some((url) => url.startsWith("/api/packs/updates"))).toBe(false);
    });

    it("keeps the search box reachable: it is still the first control after the lenses", async () => {
        serve();
        render(Knowledge, {});
        expect(await screen.findByLabelText("Search")).toBeInTheDocument();
    });
});

// ── the card that would not go away ────────────────────────────────────
//
// "After making a pack, there's a warning banner with install it / forget. I
// click either one and the warning stays there." Both endpoints were correct.
// B129 had already made the card say "is installed" — and left it a
// warning-coloured box in the alert position, which is the half anybody reads.

const DRAFT = {
    slug: "widgets",
    root: "/root/.kriko/drafts/widgets",
    files: ["pack.toml"],
    artifact: null,
    pack_id: "widgets",
    name: "Widgets",
    version: "0.1.0",
    error: "",
    installed_as: "",
};

const drafted = (over = {}) => ({
    "/api/packs/drafts": { items: [{ ...DRAFT, ...over }] },
});

describe("a drafted pack", () => {
    beforeEach(() => vi.restoreAllMocks());

    it("is an alert while it is still waiting on the reader", async () => {
        serve(drafted());
        render(Knowledge);
        const card = await screen.findByText(/was drafted for you/);
        expect(card.closest("article")?.className).toContain("notice");
    });

    it("stops being an alert once it is in the store", async () => {
        serve(drafted({ installed_as: "widgets" }));
        render(Knowledge);
        const card = await screen.findByText(/is installed/);
        expect(card.closest("article")?.className).not.toContain("notice");
    });

    it("offers hiding only once there is nothing left to decide", async () => {
        serve(drafted());
        render(Knowledge);
        await screen.findByText(/was drafted for you/);
        expect(screen.queryByText("Hide this")).toBeNull();
    });

    it("can be hidden without throwing away what the agent wrote", async () => {
        serve(drafted({ installed_as: "widgets" }));
        render(Knowledge);
        (await screen.findByText("Hide this")).click();

        await waitFor(() => expect(screen.queryByText(/is installed/)).toBeNull());
        const calls = vi.mocked(globalThis.fetch).mock.calls;
        // Written down, or it comes back on reload — which is the same
        // complaint the reader already made.
        await waitFor(() =>
            expect(
                calls.some(
                    ([url, init]) =>
                        String(url).includes("/api/settings") &&
                        String((init as RequestInit)?.body ?? "").includes("widgets"),
                ),
            ).toBe(true),
        );
        // And nothing was deleted: hiding a receipt must not destroy the one
        // copy of what the agent proposed.
        expect(
            calls.some(
                ([url, init]) =>
                    String(url).includes("/api/packs/drafts/widgets") &&
                    (init as RequestInit)?.method === "DELETE",
            ),
        ).toBe(false);
    });

    it("stays hidden when the screen is loaded again", async () => {
        serve({
            ...drafted({ installed_as: "widgets" }),
            "/api/settings": { knowledge_hidden_drafts: "widgets" },
        });
        render(Knowledge);
        await waitFor(() =>
            expect(screen.queryByText(/is installed/)).toBeNull());
    });
});
