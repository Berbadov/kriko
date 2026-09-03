import { describe, expect, it } from "vitest";
import { compare } from "./compare";
import type { Claim, StoredLookup } from "./types";

const claim = (id: string, severity = "medium", title = id): Claim => ({
    claim_id: id,
    title,
    body: "b",
    severity,
    subject: "s",
    relevance: 0.5,
    pack_id: "p",
});

const stored = (id: string, claims: Claim[]): StoredLookup => ({
    lookup_id: id,
    created_at: "2026-09-01",
    source: "form",
    label: `L-${id}`,
    request: {},
    response: { method: "exact", coverage: "FULL", claims },
});

describe("compare", () => {
    it("puts a claim both answers share on one row", () => {
        const c = compare(stored("a", [claim("x")]), stored("b", [claim("x")]));
        expect(c.rows).toHaveLength(1);
        expect(c.rows[0].left).not.toBeNull();
        expect(c.rows[0].right).not.toBeNull();
        expect(c.shared).toBe(1);
    });

    it("shows a claim only one of them has, on the correct side", () => {
        const c = compare(stored("a", [claim("x")]), stored("b", [claim("y")]));
        expect(c.onlyLeft).toBe(1);
        expect(c.onlyRight).toBe(1);
        const left = c.rows.find((r) => r.key.endsWith("x"))!;
        expect(left.right).toBeNull();
    });

    it("orders the rows worst first, so the difference that matters is at the top", () => {
        const c = compare(
            stored("a", [claim("low1", "low"), claim("high1", "high")]),
            stored("b", []),
        );
        expect(c.rows[0].key).toContain("high1");
    });

    it("aligns on claim_id where there is one, and pack+title where there is not", () => {
        const noId: Claim = { ...claim("ignored"), claim_id: undefined, title: "Same thing" };
        const c = compare(stored("a", [noId]), stored("b", [{ ...noId }]));
        expect(c.rows).toHaveLength(1);
        expect(c.shared).toBe(1);
    });

    it("compares two empty answers without inventing a difference", () => {
        const c = compare(stored("a", []), stored("b", []));
        expect(c).toEqual({ rows: [], shared: 0, onlyLeft: 0, onlyRight: 0 });
    });
});
