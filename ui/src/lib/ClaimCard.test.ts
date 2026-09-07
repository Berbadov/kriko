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

    it("keeps the author's provenance out of a buyer's card entirely", () => {
        render(ClaimCard, { claim: CLAIM, mode: "buyer" });
        expect(screen.queryByText(/relevance/)).not.toBeInTheDocument();
    });

    it("gives an author the provenance, but folded away", () => {
        render(ClaimCard, { claim: CLAIM, mode: "author" });
        const summary = screen.getByText(/Why this ranked here/);
        expect(summary).toBeInTheDocument();
        expect(summary.closest("details")).not.toHaveAttribute("open");
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
