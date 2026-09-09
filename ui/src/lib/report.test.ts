import { describe, expect, it } from "vitest";
import {
    absenceNote,
    asMarkdown,
    canCheckFacts,
    claimKey,
    confidenceNote,
    contextLines,
    emptyReason,
    factTone,
    factWord,
    groupByDomain,
    handledNote,
    orderClaims,
    questions,
    rankingNote,
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

describe("handledNote", () => {
    it("says nothing until the reader has ticked something", () => {
        const result = { method: "exact", coverage: "RISKS_FOUND", claims: [claim({})] };
        // "0 of 1 dealt with" on a freshly opened report is a scold.
        expect(handledNote(result, [])).toBe("");
    });

    it("counts against the claims actually in this answer", () => {
        const a = claim({ claim_id: "a" });
        const b = claim({ claim_id: "b" });
        const result = { method: "exact", coverage: "RISKS_FOUND", claims: [a, b] };
        expect(handledNote(result, ["a"])).toBe("1 of 2 dealt with");
        expect(handledNote(result, ["a", "b"])).toBe("All 2 dealt with");
        // A checkmark left over from a claim the pack has since dropped must
        // not push the count past the total.
        expect(handledNote(result, ["a", "b", "gone"])).toBe("All 2 dealt with");
    });
});

describe("contextLines", () => {
    it("renders whatever the adapter sent, naming no key of its own", () => {
        expect(
            contextLines({ usage_km: 180000, empty: "", missing: null }, { usage_km: "km" }),
        ).toEqual([{ key: "usage km", value: "180000 km" }]);
    });

    it("has nothing to say when the payload carried no context", () => {
        expect(contextLines(undefined)).toEqual([]);
    });
});

describe("questions", () => {
    it("is the asks, worst first, and keyed the way a checkmark is", () => {
        const list = questions({
            method: "exact",
            coverage: "RISKS_FOUND",
            claims: [
                claim({ claim_id: "l", severity: "low", advice: "Ask about the tyres." }),
                claim({ claim_id: "h", severity: "high", advice: "Ask for the receipt." }),
            ],
        });
        expect(list.map((q) => q.ask)).toEqual([
            "Ask for the receipt.",
            "Ask about the tyres.",
        ]);
        expect(list[0].key).toBe(claimKey(claim({ claim_id: "h" })));
    });

    it("falls back to a general ask rather than an empty line", () => {
        const [only] = questions({
            method: "exact",
            coverage: "RISKS_FOUND",
            claims: [claim({ advice: "" })],
        });
        expect(only.ask).toMatch(/proof this has been dealt with/);
    });
});

describe("asMarkdown", () => {
    const result = {
        method: "exact",
        coverage: "RISKS_FOUND",
        claims: [claim({ claim_id: "c1", domain: "mech", advice: "Ask for the receipt." })],
    };

    it("carries the reader's own answers, which are the half a pack cannot supply", () => {
        const text = asMarkdown(result, {
            heading: "A thing",
            notes: { c1: "done at 140k, no receipt" },
            handled: ["c1"],
        });
        expect(text).toContain("# A thing");
        expect(text).toContain("## mech");
        expect(text).toContain("**Ask:** Ask for the receipt.");
        expect(text).toContain("**Answer:** done at 140k, no receipt");
        expect(text).toContain("*Dealt with.*");
    });

    it("says what silence in it means, because the recipient has no Kriko", () => {
        expect(asMarkdown(result)).toMatch(/not that there is none/);
    });

    it("hands over an empty answer as the reason it is empty", () => {
        const text = asMarkdown({ method: "no_match", coverage: "NOT_MATCHED", claims: [] });
        expect(text).toMatch(/recognised/);
    });
});

describe("rankingNote", () => {
    it("says what a score means before quoting it", () => {
        expect(rankingNote(claim({ relevance: 0.92, trust: 0.85 }))).toBe(
            "Close match to the details given (0.92) · strong sourcing (0.85)",
        );
        expect(rankingNote(claim({ relevance: 0.2712 }))).toMatch(/^Loose match/);
    });

    it("names the rule that matched, in words rather than an identifier", () => {
        expect(rankingNote(claim({ relevance: 0.5, detection: "usage_window" }))).toContain(
            "matched by usage window",
        );
    });
});

describe("absenceNote", () => {
    it("answers the inverse question a short report raises", () => {
        expect(
            absenceNote({ method: "exact", coverage: "RISKS_FOUND", claims: [claim({})] }),
        ).toMatch(/not a risk that has been ruled out/);
    });

    it("defers to the empty-state reason when there is nothing at all", () => {
        const empty = { method: "exact", coverage: "NO_RISKS", claims: [] };
        expect(absenceNote(empty)).toBe(emptyReason(empty));
    });
});

describe("what a re-check of the sources says", () => {
    // The load-bearing sentence in this feature. A page that was rewritten is
    // a reason to go and look, not a verdict on the claim — and Kriko has no
    // authority to retract one. Overstating it once teaches the reader to
    // distrust every other badge on the card.
    it("never says a claim is false", () => {
        for (const verdict of ["quoted", "missing", "unreadable", "unreachable"]) {
            const word = factWord(verdict).toLowerCase();
            expect(word).not.toMatch(/false|wrong|refut|debunk/);
        }
        expect(factWord("missing")).toMatch(/changed/i);
    });

    // A site being down is not the pack's fault, and a red badge would say it
    // was.
    it("keeps an unreachable source neutral and a rewritten page warm", () => {
        expect(factTone("unreachable")).toBe("meta");
        expect(factTone("missing")).toBe("warn");
        expect(factTone("quoted")).toBe("ok");
    });

    it("passes an unknown verdict through rather than inventing one", () => {
        // The vocabulary lives in app/factcheck.py; a UI that mapped an
        // unseen value to "fine" would be the worst possible default.
        expect(factWord("something-new")).toBe("something-new");
        expect(factTone("something-new")).toBe("meta");
    });

    it("offers the check only where there is a page to re-read", () => {
        const base = {
            title: "t",
            body: "b",
            severity: "high",
            subject: "s",
            relevance: 1,
        };
        expect(canCheckFacts({ ...base, claim_id: "c", pack_id: "p", sources: [] })).toBe(
            false,
        );
        // /api/analyze answers with no claim_id, so there is nothing for the
        // server to look the quote up by.
        expect(
            canCheckFacts({
                ...base,
                pack_id: "p",
                sources: [{ url: "https://x", domain: "x", quote: "q", stance: "supports", tier: "" }],
            }),
        ).toBe(false);
        expect(
            canCheckFacts({
                ...base,
                claim_id: "c",
                pack_id: "p",
                sources: [{ url: "https://x", domain: "x", quote: "q", stance: "supports", tier: "" }],
            }),
        ).toBe(true);
    });
});
