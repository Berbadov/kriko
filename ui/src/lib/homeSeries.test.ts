import { describe, expect, it } from "vitest";
import { checksByDay, dayKeys, knowledgeByDay, spendByDay } from "./homeSeries";

const NOW = new Date("2026-09-30T12:00:00");

describe("homeSeries", () => {
    it("lists the last n days, oldest first, ending today", () => {
        const days = dayKeys(3, NOW);
        expect(days).toHaveLength(3);
        expect(days[2]).toBe("2026-09-30");
        expect(days[0]).toBe("2026-09-28");
    });

    it("counts lookups by the day they started, ignoring other operations", () => {
        const days = dayKeys(3, NOW);
        const rows = [
            { kind: "lookup", started_at: "2026-09-30T09:00:00" },
            { kind: "lookup", started_at: "2026-09-30T10:00:00" },
            { kind: "research", started_at: "2026-09-30T10:00:00" },
            { kind: "lookup", started_at: "2026-09-28T10:00:00" },
            { kind: "lookup", started_at: "2025-01-01T10:00:00" },
        ];
        expect(checksByDay(rows, days).map((d) => d.value)).toEqual([1, 0, 2]);
    });

    it("sums accepted findings whether the job reports a list or a number", () => {
        const days = dayKeys(2, NOW);
        const jobs = [
            { finished_at: "2026-09-30T09:00:00", result: { accepted: [1, 2, 3] } },
            { finished_at: "2026-09-30T09:30:00", result: { accepted: 4 } },
            { finished_at: "2026-09-29T09:30:00", result: { kept: 2 } },
            { finished_at: null, result: null },
        ];
        expect(knowledgeByDay(jobs, days).map((d) => d.value)).toEqual([2, 7]);
    });

    it("sums spend and reports nothing counted as null, not zero", () => {
        const days = dayKeys(2, NOW);
        const jobs = [
            { finished_at: "2026-09-30T09:00:00", result: { spent_usd: 0.25 } },
            { finished_at: "2026-09-30T09:30:00", result: { spent_usd: 0.5 } },
            { finished_at: "2026-09-29T09:30:00", result: { spent_usd: null } },
        ];
        expect(spendByDay(jobs, days)?.map((d) => d.value)).toEqual([0, 0.75]);
        expect(spendByDay([jobs[2]], days)).toBeNull();
    });
});
