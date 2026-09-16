import { render, screen, waitFor } from "@testing-library/svelte";
import { fireEvent } from "@testing-library/dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Grounding from "./Grounding.svelte";
import { stubFetch, stubFetchFailing } from "./stub-fetch";

const PROPS = { packId: "cars", claimId: "c1" };

async function openPanel() {
    render(Grounding, PROPS);
    const details = screen
        .getByText("Retained pages — what was actually kept")
        .closest("details") as HTMLDetailsElement;
    details.open = true;
    await fireEvent(details, new Event("toggle"));
}

describe("Grounding", () => {
    beforeEach(() => vi.restoreAllMocks());

    it("asks nothing until the disclosure is opened", () => {
        stubFetch({});
        render(Grounding, PROPS);
        expect(fetch).not.toHaveBeenCalled();
    });

    it("shows each piece of evidence with its own verdict, once opened", async () => {
        stubFetch({
            "/api/factcheck/grounding": {
                claim_id: "c1",
                pack_id: "cars",
                evidence: [
                    {
                        evidence_id: "e1",
                        source_id: "s1",
                        quote: "the dual-clutch mechatronic unit fails by 120k",
                        url: "https://example.com/a",
                        verdict: "grounded",
                    },
                ],
                not_kept: 0,
                ungrounded: 0,
            },
        });
        await openPanel();
        await waitFor(() =>
            expect(screen.getByText(/dual-clutch mechatronic unit/)).toBeInTheDocument(),
        );
        expect(screen.getByText("Quote found in the retained page")).toBeInTheDocument();
    });

    it("never renders not_kept as a pass", async () => {
        stubFetch({
            "/api/factcheck/grounding": {
                claim_id: "c1",
                pack_id: "cars",
                evidence: [
                    {
                        evidence_id: "e1",
                        source_id: "s1",
                        quote: "quote",
                        url: "",
                        verdict: "not_kept",
                    },
                ],
                not_kept: 1,
                ungrounded: 0,
            },
        });
        await openPanel();
        const badge = await screen.findByText("No page was kept to check this against");
        expect(badge.className).not.toContain("fact-ok");
        expect(badge.className).toContain("fact-meta");
        // A source with nothing kept has nothing to view.
        expect(screen.queryByRole("button", { name: "View the retained page" })).toBeNull();
    });

    it("shows an explicit empty state when the claim has no evidence", async () => {
        stubFetch({
            "/api/factcheck/grounding": {
                claim_id: "c1",
                pack_id: "cars",
                evidence: [],
                not_kept: 0,
                ungrounded: 0,
            },
        });
        await openPanel();
        await waitFor(() =>
            expect(screen.getByText("No evidence recorded for this claim.")).toBeInTheDocument(),
        );
    });

    it("names the failure rather than rendering nothing when the check itself fails", async () => {
        stubFetchFailing(500);
        await openPanel();
        await waitFor(() =>
            expect(screen.getByText(/bug in Kriko/)).toBeInTheDocument(),
        );
    });

    it("fetches and shows the retained page text on request", async () => {
        stubFetch({
            "/api/factcheck/grounding": {
                claim_id: "c1",
                pack_id: "cars",
                evidence: [
                    {
                        evidence_id: "e1",
                        source_id: "s1",
                        quote: "quote",
                        url: "https://example.com/a",
                        verdict: "grounded",
                    },
                ],
                not_kept: 0,
                ungrounded: 0,
            },
            "/api/factcheck/document": {
                source_id: "s1",
                pack_id: "cars",
                url: "https://example.com/a",
                text: "the full retained page text",
                chars: 28,
                retained_at: "2026-09-01T00:00:00Z",
            },
        });
        await openPanel();
        const view = await screen.findByRole("button", { name: "View the retained page" });
        await fireEvent.click(view);
        await waitFor(() =>
            expect(screen.getByText("the full retained page text")).toBeInTheDocument(),
        );
        // And it can be hidden again without losing the evidence list.
        const hide = screen.getByRole("button", { name: "Hide the retained page" });
        await fireEvent.click(hide);
        await waitFor(() =>
            expect(screen.queryByText("the full retained page text")).toBeNull(),
        );
    });

    it("says plainly when this install kept no copy of the page", async () => {
        stubFetch({
            "/api/factcheck/grounding": {
                claim_id: "c1",
                pack_id: "cars",
                evidence: [
                    {
                        evidence_id: "e1",
                        source_id: "s1",
                        quote: "quote",
                        url: "https://example.com/a",
                        verdict: "ungrounded",
                    },
                ],
                not_kept: 0,
                ungrounded: 1,
            },
            "/api/factcheck/document": { status: 404, body: '{"detail":"not_kept: no retained page"}' },
        });
        await openPanel();
        const view = await screen.findByRole("button", { name: "View the retained page" });
        await fireEvent.click(view);
        await waitFor(() =>
            expect(screen.getByText("No page was kept for this source.")).toBeInTheDocument(),
        );
    });
});
