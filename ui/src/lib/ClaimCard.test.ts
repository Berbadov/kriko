import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import ClaimCard from "./ClaimCard.svelte";
import type { Claim } from "./types";

const CLAIM: Claim = {
    claim_id: "c1",
    title: "A known risk",
    body: "What goes wrong.",
    advice: "Ask for the receipt.",
    severity: "high",
    subject: "S",
    relevance: 0.9,
    pack_id: "p",
    why: ["mileage over the interval"],
    sources: [{ domain: "d.example", quote: "q", stance: "supports", tier: "forum" }],
};

describe("ClaimCard", () => {
    it("says what to ask, because that is the reader's next action", () => {
        render(ClaimCard, { claim: CLAIM });
        expect(screen.getByText("Ask for the receipt.")).toBeInTheDocument();
    });

    it("gives everyone the provenance, folded away (B165)", () => {
        render(ClaimCard, { claim: CLAIM });
        const summary = screen.getByText(/Why this ranked here/);
        expect(summary).toBeInTheDocument();
        expect(summary.closest("details")).not.toHaveAttribute("open");
        // The raw values an author audits a rank with are there for all.
        expect(screen.getByText(/relevance 0.9/)).toBeInTheDocument();
        expect(screen.getByText("mileage over the interval")).toBeInTheDocument();
    });

    it("names each source's tier and stance for everyone (B165)", () => {
        render(ClaimCard, { claim: CLAIM });
        expect(screen.getByText("d.example · forum · supports")).toBeInTheDocument();
    });

    it("marks a handled claim so the eye can skip it", () => {
        const { container } = render(ClaimCard, {
            claim: CLAIM,
            checked: true,
            onCheck: () => {},
        });
        expect(container.querySelector(".card.risk.done")).not.toBeNull();
    });

    it("does not offer a checkbox where nothing can record it", () => {
        render(ClaimCard, { claim: CLAIM });
        expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    });
});

describe("checking what the source says now", () => {
    const CITED: Claim = {
        ...CLAIM,
        sources: [
            {
                url: "https://d.example/a",
                domain: "d.example",
                quote: "q",
                stance: "supports",
                tier: "forum",
            },
        ],
    };

    it("offers the check on the card, not inside the sources fold", () => {
        // "Is this still true" is the question a reader has while reading the
        // claim. Behind a disclosure triangle it is a button nobody finds.
        render(ClaimCard, { claim: CITED, onCheckFacts: () => {} });
        // Named with the claim's title (check-26): eight of these on one
        // report all said "Check the source" with nothing telling them apart.
        expect(
            screen.getByRole("button", { name: `Check the source: ${CITED.title}` }),
        ).toBeVisible();
    });

    it("says nothing at all when there is no page to re-read", () => {
        render(ClaimCard, { claim: CLAIM, onCheckFacts: () => {} });
        expect(screen.queryByRole("button", { name: /Check the source/ })).toBeNull();
    });

    it("reports a rewritten page as changed, never as false", () => {
        const { container } = render(ClaimCard, {
            claim: CITED,
            onCheckFacts: () => {},
            factCheck: {
                pack_id: "p",
                claim_id: "c1",
                verdict: "missing",
                detail: "the page no longer carries this quote",
                sources: [],
                subject_id: "s",
                title: "A known risk",
                checked_at: "2026-09-09T10:00:00+00:00",
            },
        });
        expect(screen.getByText("Source has changed")).toBeInTheDocument();
        // With a date, always: reassurance with no "when" on it ages badly.
        expect(screen.getByText(/checked 2026-09-09/)).toBeInTheDocument();
        // Scoped to the badge line: the claim's own body is allowed to use
        // any word it likes, and this is about what the app asserts.
        expect(container.querySelector(".fact")?.textContent).not.toMatch(
            /false|wrong|refut/i,
        );
    });

    it("shows the press as taking time, because reading a page does", () => {
        render(ClaimCard, { claim: CITED, onCheckFacts: () => {}, checkingFacts: true });
        expect(screen.getByRole("button", { name: /Reading the source/ })).toBeDisabled();
    });
});
