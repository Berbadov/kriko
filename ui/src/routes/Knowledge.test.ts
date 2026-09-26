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
};

const MARK = {
    pack_id: "org.kriko.cars",
    claim_id: "c1",
    verdict: "wrong",
    note: "",
    subject_id: "s1",
    title: "Timing chain tensioner wear",
    created_at: "2026-09-06T10:00:00Z",
    updated_at: "2026-09-06T10:00:00Z",
};

function serve(over: Record<string, unknown> = {}) {
    return stubFetch({
        "/api/status": STATUS,
        "/api/packs": [PACK],
        "/api/subjects": [],
        "/api/packs/org.kriko.cars/gaps": [],
        "/api/marks": { items: [], counts: {}, verdicts: ["useful", "not_applicable", "wrong"] },
        "/api/marks/signals": { research: [], matching: [] },
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

    it("opens on the lens the route named, so an old bookmark still lands right", async () => {
        serve();
        render(Knowledge, { lens: "marked" });
        await waitFor(() =>
            expect(
                screen.getByRole("tab", { name: /What readers said/ }),
            ).toHaveAttribute("aria-selected", "true"),
        );
    });

    it("names every verdict even at zero, so the strip does not change shape", async () => {
        serve();
        render(Knowledge, { lens: "marked" });
        await waitFor(() => expect(screen.getByText("Useful")).toBeInTheDocument());
        // "Not mine" and "Wrong" are separate on purpose: one is a matching
        // problem, the other a knowledge problem.
        expect(screen.getByText("Not mine")).toBeInTheDocument();
        expect(screen.getByText("Wrong")).toBeInTheDocument();
    });

    it("tells an author what a reader called wrong, by the claim's own words", async () => {
        serve({
            "/api/marks": {
                items: [MARK],
                counts: { useful: 0, not_applicable: 0, wrong: 1 },
                verdicts: ["useful", "not_applicable", "wrong"],
            },
        });
        render(Knowledge, { lens: "marked" });
        await waitFor(() =>
            expect(screen.getByText("Timing chain tensioner wear")).toBeInTheDocument(),
        );
        // The title is stored on the mark rather than looked up, so it still
        // reads after the pack that held the claim is uninstalled.
        expect(screen.getByRole("button", { name: "Forget" })).toBeInTheDocument();
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
        const marked = screen.getByRole("tab", { name: /What readers said/ });
        await fireEvent.keyDown(gaps, { key: "End" });
        expect(marked).toHaveAttribute("aria-selected", "true");
        expect(marked).toHaveFocus();
    });

    it("explains where verdicts come from when there are none", async () => {
        serve();
        render(Knowledge, { lens: "marked" });
        await waitFor(() =>
            expect(screen.getByText(/No one has marked anything yet/)).toBeInTheDocument(),
        );
        expect(screen.getByText(/browser extension/)).toBeInTheDocument();
    });

    it("turns a pile of wrong verdicts into something an author can start", async () => {
        serve({
            "/api/marks/signals": {
                research: [
                    {
                        subject_id: "s1",
                        pack_id: "org.kriko.cars",
                        count: 2,
                        notes: ["my mechanic says otherwise"],
                        claim_ids: ["c1", "c2"],
                    },
                ],
                matching: [],
            },
        });
        render(Knowledge, { lens: "marked" });
        await waitFor(() =>
            expect(screen.getByText(/Worth researching again/)).toBeInTheDocument(),
        );
        expect(screen.getByText(/2 called wrong/)).toBeInTheDocument();
        // The reader's own words travel with the queue: they are the most
        // useful thing on a mark and the point of collecting one.
        expect(screen.getByText(/my mechanic says otherwise/)).toBeInTheDocument();
        // And a way to act on it, reusing the same brief the gaps lens starts.
        expect(screen.getAllByRole("button", { name: "Research" }).length).toBe(1);
    });

    it("keeps a mismatch out of the research queue and names the door instead", async () => {
        serve({
            "/api/marks/signals": {
                research: [],
                matching: [
                    {
                        subject_id: "s2",
                        pack_id: "org.kriko.cars",
                        count: 1,
                        notes: [],
                        claim_ids: ["c9"],
                        sources: { url: 3 },
                    },
                ],
            },
        });
        render(Knowledge, { lens: "marked" });
        await waitFor(() =>
            expect(screen.getByText(/Matched the wrong thing/)).toBeInTheDocument(),
        );
        // Researching it again would fix nothing, so it is offered no brief.
        expect(screen.queryByRole("button", { name: "Research" })).toBeNull();
        expect(screen.getByText(/suspect what the page was read as/)).toBeInTheDocument();
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
