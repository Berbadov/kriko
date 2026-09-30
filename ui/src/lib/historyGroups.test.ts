import { describe, expect, it } from "vitest";
import { foldRepeats, groupByCategory } from "./historyGroups";
import type { HistoryItem } from "./types";

const item = (id: string, label: string, category = "", created = "2026-09-01"): HistoryItem => ({
    lookup_id: id,
    created_at: created,
    source: "url",
    label,
    claim_count: 1,
    category,
    packs: category ? [{ pack_id: "p", name: category }] : [],
});

describe("foldRepeats", () => {
    it("folds three identical rows into one entry that opens the newest", () => {
        const entries = foldRepeats([
            item("c", "MacBook Air"),
            item("b", "MacBook Air"),
            item("a", "macbook air "),
        ]);
        expect(entries).toHaveLength(1);
        expect(entries[0].latest.lookup_id).toBe("c");
        expect(entries[0].checks.map((one) => one.lookup_id)).toEqual(["c", "b", "a"]);
    });

    it("keeps different products apart", () => {
        expect(foldRepeats([item("a", "One"), item("b", "Two")])).toHaveLength(2);
    });

    it("does not fold the same label across two categories", () => {
        const entries = foldRepeats([item("a", "Same", "Alpha"), item("b", "Same", "Beta")]);
        expect(entries).toHaveLength(2);
    });
});

describe("groupByCategory", () => {
    it("groups by the category the row carries and counts every check", () => {
        const groups = groupByCategory([
            item("a", "One", "Alpha"),
            item("b", "One", "Alpha"),
            item("c", "Two", "Beta"),
        ]);
        expect(groups.map((g) => [g.category, g.entries.length, g.total])).toEqual([
            ["Alpha", 1, 2],
            ["Beta", 1, 1],
        ]);
    });

    it("puts checks no pack answered last, however recent", () => {
        const groups = groupByCategory([item("a", "Loose"), item("b", "Kept", "Alpha")]);
        expect(groups.map((g) => g.category)).toEqual(["Alpha", ""]);
    });
});
