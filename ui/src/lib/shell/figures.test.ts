import { describe, expect, it } from "vitest";
import { EMPTY, type Readings } from "./instruments";
import { count, figures, money } from "./figures";

const reading = (over: Partial<Readings> = {}): Readings => ({ ...EMPTY, ...over });

describe("which rows carry a number", () => {
    it("says nothing at all before the first read lands", () => {
        expect(figures(EMPTY)).toEqual({});
    });

    it("draws zero claims, because an empty installation is the fact worth telling", () => {
        expect(figures(reading({ claims: 0 })).knowledge?.text).toBe("0");
    });

    it("draws no job count when nothing is running", () => {
        expect(figures(reading({ running: 0 })).activity).toBeUndefined();
    });

    it("marks a running job as live, so it is read differently from a total", () => {
        const figure = figures(reading({ running: 2 })).activity;
        expect(figure?.text).toBe("2");
        expect(figure?.live).toBe(true);
        expect(figure?.title).toBe("2 jobs running");
    });

    it("counts one job in the singular", () => {
        expect(figures(reading({ running: 1 })).activity?.title).toBe("1 job running");
    });

    it("leaves spend blank when nothing could be priced, rather than drawing zero", () => {
        // The dangerous one. An unpriced model meters tokens and reports no
        // cost; a rail that renders that as $0.00 says a paid run was free.
        expect(figures(reading({ spentUsd: null })).agents).toBeUndefined();
        expect(figures(reading({ spentUsd: 0 })).agents?.text).toBe("$0.00");
    });

    it("hangs a sparkline off spend only when there is a shape to draw", () => {
        expect(figures(reading({ spentUsd: 1, trail: [0.4] })).agents?.trail)
            .toBeUndefined();
        expect(figures(reading({ spentUsd: 1, trail: [0.4, 0.6] })).agents?.trail)
            .toEqual([0.4, 0.6]);
    });

    it("gives every figure a name, because a bare number is not a fact", () => {
        const all = figures(reading({ claims: 12, running: 1, spentUsd: 3 }));
        for (const [row, figure] of Object.entries(all)) {
            expect(figure.title, row).not.toBe(figure.text);
            expect(figure.title.length, row).toBeGreaterThan(figure.text.length);
        }
    });
});

describe("how the numbers are written", () => {
    it("separates thousands, because five unbroken digits is a password", () => {
        expect(count(1620)).toBe("1,620");
    });

    it("keeps cents under ten dollars and drops them above", () => {
        // $0.34 and $0.02 are a different decision; $41 and $41.27 are not.
        expect(money(0.02)).toBe("$0.02");
        expect(money(9.99)).toBe("$9.99");
        expect(money(41.27)).toBe("$41");
    });
});
