import { describe, expect, it } from "vitest";

import { count } from "./plural";

describe("count", () => {
    it("says zero in words, because a bare 0 reads as a count that failed", () => {
        expect(count(0, "claim")).toBe("no claims");
        expect(count(0, "subject")).toBe("no subjects");
    });

    it("drops the s at one", () => {
        expect(count(1, "claim")).toBe("1 claim");
    });

    it("keeps the digit above one", () => {
        expect(count(2, "claim")).toBe("2 claims");
        expect(count(736, "subject")).toBe("736 subjects");
    });

    it("takes an irregular plural rather than guessing at one", () => {
        expect(count(2, "entry", "entries")).toBe("2 entries");
        expect(count(1, "entry", "entries")).toBe("1 entry");
        expect(count(0, "entry", "entries")).toBe("no entries");
    });

    it("never emits the parenthesis it exists to remove", () => {
        for (const n of [0, 1, 2, 17]) {
            expect(count(n, "claim")).not.toContain("(s)");
        }
    });
});
