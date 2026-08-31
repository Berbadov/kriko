import { describe, expect, it } from "vitest";
import { signalNote, tieNote } from "./health";
import type { ClaimHealth } from "./types";

const claim = (over: Partial<ClaimHealth> = {}): ClaimHealth => ({
    claim_id: "c1",
    subject_id: "s1",
    subject_label: "Subject",
    pack_id: "tools",
    title: "A claim",
    refuted_by: 0,
    independent_sources: 3,
    best_tier: "manufacturer",
    best_trust: 0.9,
    oldest_retrieved_at: "2026-01-01",
    concern: [0, 3, 0.9, "2026-01-01"],
    ...over,
});

describe("signalNote", () => {
    it("names contradiction first, ahead of thinness", () => {
        expect(signalNote(claim({ refuted_by: 2, independent_sources: 1 }))).toBe(
            "a source in the pack contradicts this claim",
        );
    });
    it("calls a single-source claim thin", () => {
        expect(signalNote(claim({ independent_sources: 1 }))).toBe(
            "only one independent source supports this",
        );
    });
    it("calls a low-tier best source weak", () => {
        expect(signalNote(claim({ best_trust: 0.3 }))).toBe(
            "the best supporting source is a low-trust tier",
        );
    });
    it("says nothing about a well-supported claim", () => {
        expect(signalNote(claim())).toBe("");
    });
});

describe("tieNote", () => {
    it("is silent when nothing ties", () => {
        expect(tieNote([claim(), claim({ concern: [1, 1, 0.2, null] })])).toBe("");
    });
    it("warns when the top of the list ties on every signal", () => {
        expect(tieNote([claim(), claim(), claim({ concern: [9] })])).toContain(
            "2 of the claims shown tie on every signal",
        );
    });
    it("is silent on an empty list", () => {
        expect(tieNote([])).toBe("");
    });
});
