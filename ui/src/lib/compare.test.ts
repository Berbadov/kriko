import { describe, expect, it } from "vitest";
import { compareMany } from "./compare";
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

describe("compareMany", () => {
    it("puts a claim both answers share on one row", () => {
        const c = compareMany([stored("a", [claim("x")]), stored("b", [claim("x")])]);
        expect(c.rows).toHaveLength(1);
        expect(c.rows[0].cells.every(Boolean)).toBe(true);
        expect(c.shared).toBe(1);
    });

    it("shows a claim only one of them has, on the correct side", () => {
        const c = compareMany([stored("a", [claim("x")]), stored("b", [claim("y")])]);
        expect(c.only).toEqual([1, 1]);
        const left = c.rows.find((r) => r.key.endsWith("x"))!;
        expect(left.cells[1]).toBeNull();
    });

    it("orders the rows worst first, so the difference that matters is at the top", () => {
        const c = compareMany([
            stored("a", [claim("low1", "low"), claim("high1", "high")]),
            stored("b", []),
        ]);
        expect(c.rows[0].key).toContain("high1");
    });

    it("aligns on claim_id where there is one, and pack+title where there is not", () => {
        const noId: Claim = { ...claim("ignored"), claim_id: undefined, title: "Same thing" };
        const c = compareMany([stored("a", [noId]), stored("b", [{ ...noId }])]);
        expect(c.rows).toHaveLength(1);
        expect(c.shared).toBe(1);
    });

    it("compares empty answers without inventing a difference", () => {
        const c = compareMany([stored("a", []), stored("b", [])]);
        expect(c).toEqual({ rows: [], shared: 0, only: [0, 0] });
    });

    it("lines up a third answer, which is what shopping actually looks like", () => {
        const c = compareMany([
            stored("a", [claim("x"), claim("y")]),
            stored("b", [claim("x")]),
            stored("c", [claim("z", "high")]),
        ]);
        // Worst first: c's serious one leads, and every row is three wide so
        // the columns cannot drift.
        expect(c.rows[0].key).toContain("z");
        expect(c.rows.every((row) => row.cells.length === 3)).toBe(true);
        expect(c.shared).toBe(0);
        expect(c.only).toEqual([1, 0, 1]);
    });

    it("says nothing is shared when there is only one answer to compare", () => {
        const c = compareMany([stored("a", [claim("x")])]);
        // A single answer has every claim "only on one side", and that is the
        // honest reading — the screen refuses to draw a comparison from it.
        expect(c.shared).toBe(1);
        expect(c.only).toEqual([1]);
    });
});
