import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import BenchChart from "./BenchChart.svelte";
import type { BenchPoint } from "./bench";

const point = (over: Partial<BenchPoint> = {}): BenchPoint => ({
    protocol: "standard",
    batchSize: 1,
    contextChars: 12000,
    preamble: "",
    hallucinationRate: 0.08,
    hallucinationInterval: [0.02, 0.2],
    usdPerAcceptedClaim: 0.05,
    runs: 4,
    chosen: true,
    ...over,
});

describe("BenchChart", () => {
    it("plots a graded, priced protocol as a scatter point", () => {
        render(BenchChart, { llm: "model-a", points: [point()] });
        expect(
            screen.getByRole("img", { name: /model-a: cost per accepted claim/ }),
        ).toBeInTheDocument();
    });

    it("says so instead of drawing a fake position when nothing is priced", () => {
        render(BenchChart, {
            llm: "model-a",
            points: [point({ usdPerAcceptedClaim: null })],
        });
        expect(screen.getByText(/missing a priced run/)).toBeInTheDocument();
        expect(screen.queryByRole("img")).toBeNull();
    });

    it("says so instead of an empty chart when nothing has been graded at all", () => {
        render(BenchChart, { llm: "model-a", points: [] });
        expect(screen.getByText("No graded run for this LLM yet.")).toBeInTheDocument();
    });

    it("keeps every measured protocol in the table view, priced or not", () => {
        render(BenchChart, {
            llm: "model-a",
            points: [point({ protocol: "standard" }), point({ protocol: "wide", chosen: false, usdPerAcceptedClaim: null })],
        });
        expect(screen.getByText("standard (chosen)")).toBeInTheDocument();
        expect(screen.getByText("wide")).toBeInTheDocument();
    });
});
