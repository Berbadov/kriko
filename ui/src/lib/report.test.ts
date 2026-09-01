import { describe, expect, it } from "vitest";
import {
    claimKey,
    confidenceNote,
    emptyReason,
    groupByDomain,
    orderClaims,
    severityWord,
    sourceSummary,
} from "./report";
import type { Claim } from "./types";

const claim = (over: Partial<Claim>): Claim => ({
    title: "t",
    body: "b",
    severity: "medium",
    subject: "s",
    pack_id: "p",
    relevance: 0.1,
    ...over,
});

describe("orderClaims", () => {
    it("puts consequence above score, unlike the engine's own order", () => {
        const ordered = orderClaims([
            claim({ title: "minor but likely", severity: "low", relevance: 0.9 }),
            claim({ title: "serious but unlikely", severity: "high", relevance: 0.1 }),
        ]);
        expect(ordered.map((c) => c.title)).toEqual([
            "serious but unlikely",
            "minor but likely",
        ]);
    });

    it("breaks a tie on relevance, then on title, so the order is total", () => {
        const ordered = orderClaims([
            claim({ title: "b", relevance: 0.5 }),
            claim({ title: "a", relevance: 0.5 }),
            claim({ title: "c", relevance: 0.6 }),
        ]);
        expect(ordered.map((c) => c.title)).toEqual(["c", "a", "b"]);
    });

    it("does not mutate the payload it was handed", () => {
        const claims = [claim({ title: "x", severity: "low" }), claim({ title: "y", severity: "high" })];
        orderClaims(claims);
        expect(claims.map((c) => c.title)).toEqual(["x", "y"]);
    });
});

describe("groupByDomain", () => {
    it("groups by the pack's own domain and leads with the worst group", () => {
        const groups = groupByDomain([
            claim({ title: "cosmetic", domain: "body", severity: "low" }),
            claim({ title: "seized", domain: "mech", severity: "high" }),
            claim({ title: "noisy", domain: "mech", severity: "medium" }),
        ]);
        expect(groups.map((g) => g.domain)).toEqual(["mech", "body"]);
        expect(groups[0].claims.map((c) => c.title)).toEqual(["seized", "noisy"]);
    });

    it("files a claim with no domain rather than dropping it", () => {
        expect(groupByDomain([claim({})])).toEqual([
            { domain: "other", claims: [claim({})] },
        ]);
    });
});

describe("claimKey", () => {
    it("prefers the engine's id and falls back to a pack-scoped title", () => {
        expect(claimKey(claim({ claim_id: "c1" }))).toBe("c1");
        // /api/analyze returns no claim_id, and a checkmark has to survive there.
        expect(claimKey(claim({ title: "Timing belt", pack_id: "cars" }))).toBe(
            "cars:Timing belt",
        );
    });
});

describe("sourceSummary", () => {
    it("counts agreement in a sentence and names disagreement", () => {
        const src = (stance: string) => ({
            domain: "d",
            quote: "q",
            tier: "forum_ugc",
            stance,
        });
        expect(sourceSummary(claim({ sources: [src("supports")] }))).toBe(
            "1 source reports this",
        );
        expect(
            sourceSummary(
                claim({ sources: [src("supports"), src("supports"), src("refutes")] }),
            ),
        ).toBe("2 sources report this, 1 disagrees");
    });

    it("explains a sourceless claim instead of saying zero sources", () => {
        expect(sourceSummary(claim({}))).toMatch(/service-interval/);
    });
});

describe("emptyReason", () => {
    it("distinguishes an unrecognised thing from an unresearched one", () => {
        expect(emptyReason({ method: "no_match", claims: [], coverage: "NOT_MATCHED" }))
            .toMatch(/recognised/);
        expect(emptyReason({ method: "exact", claims: [], coverage: "NO_RISKS" }))
            .toMatch(/coverage gap, not a clean bill of health/);
    });
});

describe("wording", () => {
    it("says severity in words a buyer reads as urgency", () => {
        expect(severityWord("high")).toBe("Serious");
        expect(severityWord("weird")).toBe("weird");
    });

    it("states the match in a sentence rather than an enum", () => {
        expect(confidenceNote({ method: "exact", coverage: "RISKS_FOUND", claims: [] }))
            .toBe("Matched exactly on the details given, coverage risks found.");
    });
});
