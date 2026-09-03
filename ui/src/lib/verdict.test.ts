import { describe, expect, it } from "vitest";
import type { Claim, LookupResult } from "./types";
import { severityShare, verdictFor } from "./verdict";

const claim = (severity: string, id: string): Claim => ({
    claim_id: id,
    title: `t-${id}`,
    body: "b",
    severity,
    subject: "s",
    relevance: 0.5,
    pack_id: "p",
});

const result = (claims: Claim[], over: Partial<LookupResult> = {}): LookupResult => ({
    method: "exact",
    coverage: "FULL",
    claims,
    ...over,
});

describe("verdictFor", () => {
    it("leads with the serious count when there is one", () => {
        const v = verdictFor(result([claim("high", "a"), claim("low", "b")]), []);
        expect(v.tone).toBe("alarm");
        expect(v.headline).toMatch(/1 serious/);
        expect(v.counts).toMatchObject({ total: 2, high: 1, low: 1, handled: 0 });
    });

    it("does not cry alarm over minor items alone", () => {
        const v = verdictFor(result([claim("low", "a"), claim("low", "b")]), []);
        expect(v.tone).toBe("caution");
        // "none serious" is the useful thing to say here — it is factual and
        // the risks are still listed below. What must not appear is a serious
        // *count*, which is the alarm this case exists to rule out.
        expect(v.headline).not.toMatch(/\d+ serious/);
        expect(v.headline).toMatch(/none serious/);
    });

    it("counts what the reader has already handled", () => {
        const v = verdictFor(result([claim("high", "a"), claim("high", "b")]), ["a"]);
        expect(v.counts.handled).toBe(1);
        expect(v.headline).toMatch(/1 handled/);
    });

    it("separates 'we could not identify it' from 'we know nothing about it'", () => {
        const unmatched = verdictFor(
            result([], { coverage: "NOT_MATCHED", method: "no_match" }),
            [],
        );
        expect(unmatched.tone).toBe("unknown");
        expect(unmatched.note).toMatch(/No installed pack recognised/);

        const empty = verdictFor(result([], { coverage: "FULL" }), []);
        expect(empty.tone).toBe("unknown");
        expect(empty.note).toMatch(/coverage gap, not a clean bill of health/);
    });

    it("never claims a clean bill of health from an empty answer", () => {
        const v = verdictFor(result([], { coverage: "FULL" }), []);
        expect(v.headline).not.toMatch(/nothing wrong|clean|fine/i);
    });

    it("quotes how the match was made, so a count is never read alone", () => {
        const v = verdictFor(result([claim("high", "a")], { method: "family" }), []);
        expect(v.note).toMatch(/Matched by family/);
    });

    it("carries no money in it, because the payload has none", () => {
        const v = verdictFor(result([claim("high", "a")]), []);
        expect(`${v.headline} ${v.note}`).not.toMatch(/[€$₺£]|\bTL\b|cost|price/i);
    });
});

describe("severityShare", () => {
    it("is proportional and ordered worst-first", () => {
        const share = severityShare({ total: 4, high: 2, medium: 1, low: 1, handled: 0 });
        expect(share.map((s) => s.severity)).toEqual(["high", "medium", "low"]);
        expect(share[0].percent).toBe(50);
    });

    it("is empty when there is nothing to divide", () => {
        expect(
            severityShare({ total: 0, high: 0, medium: 0, low: 0, handled: 0 }),
        ).toEqual([]);
    });
});
