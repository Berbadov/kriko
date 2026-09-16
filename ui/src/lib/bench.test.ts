import { describe, expect, it } from "vitest";
import {
    formatInterval,
    formatPct,
    formatUsd,
    hallucinationSeverity,
    plottable,
    pointsByLlm,
} from "./bench";
import type { Bench } from "./types";

const bench = (over: Partial<Bench> = {}): Bench => ({
    runs: [],
    verdict: {},
    scored: { groups: [] },
    summary: [],
    cases: [],
    protocols: [
        { name: "standard", context_chars: 12000, batch_size: 1, preamble: "" },
        { name: "wide", context_chars: 10000, batch_size: 4, preamble: "" },
    ],
    chosen: {},
    readout: [],
    ...over,
});

describe("hallucinationSeverity", () => {
    it("has no severity for an unmeasured rate", () => {
        expect(hallucinationSeverity(null)).toBe("");
    });
    it("bands a low rate as low", () => {
        expect(hallucinationSeverity(0.02)).toBe("low");
        expect(hallucinationSeverity(0.05)).toBe("low");
    });
    it("bands a middling rate as medium", () => {
        expect(hallucinationSeverity(0.1)).toBe("medium");
        expect(hallucinationSeverity(0.15)).toBe("medium");
    });
    it("bands a high rate as high", () => {
        expect(hallucinationSeverity(0.16)).toBe("high");
        expect(hallucinationSeverity(0.9)).toBe("high");
    });
});

describe("formatting", () => {
    it("shows an em dash for a value nobody measured, never a zero", () => {
        expect(formatUsd(null)).toBe("—");
        expect(formatPct(null)).toBe("—");
    });
    it("formats a measured cost and rate", () => {
        expect(formatUsd(0.0123)).toBe("$0.0123");
        expect(formatPct(0.234)).toBe("23.4%");
    });
    it("formats a Wilson interval as a percent range", () => {
        expect(formatInterval([0.1, 0.3])).toBe("10–30%");
        expect(formatInterval(null)).toBe("");
    });
});

describe("pointsByLlm", () => {
    it("joins a scored group to its priced summary row and the chosen flag", () => {
        const data = bench({
            chosen: { "model-a": "wide" },
            summary: [
                {
                    plane: "offline", llm: "model-a", protocol: "wide", runs: 3,
                    ms: 100, tokens: 500, usd: 0.6, documents: 3, findings: 10,
                    accepted: 6, refused: 2, failures: 0, acceptance: 0.75,
                },
            ],
            scored: {
                groups: [
                    {
                        plane: "offline", llm: "model-a", protocol: "wide", runs: 3,
                        found: 8, wanted: 10, produced: 10, hallucinated: 1,
                        recall: 0.8, recall_interval: [0.5, 0.95],
                        hallucination_rate: 0.1, hallucination_interval: [0.02, 0.4],
                    },
                ],
            },
        });
        const byLlm = pointsByLlm(data);
        expect(Object.keys(byLlm)).toEqual(["model-a"]);
        const [point] = byLlm["model-a"];
        expect(point.protocol).toBe("wide");
        expect(point.batchSize).toBe(4);
        expect(point.contextChars).toBe(10000);
        expect(point.chosen).toBe(true);
        expect(point.usdPerAcceptedClaim).toBeCloseTo(0.1);
        expect(point.hallucinationRate).toBe(0.1);
    });

    it("leaves cost null when no run in the group was ever priced", () => {
        const data = bench({
            summary: [
                {
                    plane: "offline", llm: "model-a", protocol: "standard", runs: 2,
                    ms: 0, tokens: 0, usd: null, documents: 0, findings: 0,
                    accepted: 4, refused: 0, failures: 0, acceptance: 1,
                },
            ],
            scored: {
                groups: [
                    {
                        plane: "offline", llm: "model-a", protocol: "standard", runs: 2,
                        found: 4, wanted: 4, produced: 4, hallucinated: 0,
                        recall: 1, recall_interval: [0.5, 1],
                        hallucination_rate: 0, hallucination_interval: [0, 0.4],
                    },
                ],
            },
        });
        expect(pointsByLlm(data)["model-a"][0].usdPerAcceptedClaim).toBeNull();
    });

    it("skips a scored group with no gold-graded hallucination rate", () => {
        const data = bench({
            scored: {
                groups: [
                    {
                        plane: "offline", llm: "model-a", protocol: "standard", runs: 1,
                        found: 0, wanted: 0, produced: 0, hallucinated: 0,
                        recall: null, recall_interval: null,
                        hallucination_rate: null, hallucination_interval: null,
                    },
                ],
            },
        });
        expect(pointsByLlm(data)).toEqual({});
    });
});

describe("plottable", () => {
    it("keeps only points with a priced cost", () => {
        const points = [
            { usdPerAcceptedClaim: 0.1 } as ReturnType<typeof pointsByLlm>[string][number],
            { usdPerAcceptedClaim: null } as ReturnType<typeof pointsByLlm>[string][number],
        ];
        expect(plottable(points)).toHaveLength(1);
    });
});
