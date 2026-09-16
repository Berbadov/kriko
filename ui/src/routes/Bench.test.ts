import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Bench from "./Bench.svelte";
import { stubFetch, stubFetchFailing } from "../lib/stub-fetch";
import type { Bench as BenchPayload } from "../lib/types";

const EMPTY: BenchPayload = {
    runs: [],
    verdict: {},
    scored: { groups: [] },
    summary: [],
    cases: [{ id: "c1" }, { id: "c2" }],
    protocols: [{ name: "standard", context_chars: 12000, batch_size: 1, preamble: "" }],
    chosen: {},
    readout: [],
};

const ONE_MEASURED: BenchPayload = {
    ...EMPTY,
    readout: [
        {
            llm: "model-a",
            protocol: "standard",
            batch_size: 1,
            context_chars: 12000,
            preamble: "",
            search_provider: "brave",
            usd_per_accepted_claim: 0.041,
            hallucination_rate: 0.08,
            hallucination_interval: [0.02, 0.2],
            runs: 4,
            note: "",
        },
        {
            llm: "model-b",
            protocol: "standard",
            batch_size: 1,
            context_chars: 12000,
            preamble: "",
            search_provider: "",
            usd_per_accepted_claim: null,
            hallucination_rate: null,
            hallucination_interval: null,
            runs: 1,
            note: "fewer than 2 runs measured for this model",
        },
    ],
    chosen: { "model-a": "standard" },
    summary: [
        {
            plane: "offline", llm: "model-a", protocol: "standard", runs: 4,
            ms: 100, tokens: 500, usd: 0.164, documents: 4, findings: 10,
            accepted: 4, refused: 1, failures: 0, acceptance: 0.8,
        },
    ],
    scored: {
        groups: [
            {
                plane: "offline", llm: "model-a", protocol: "standard", runs: 4,
                found: 9, wanted: 10, produced: 10, hallucinated: 1,
                recall: 0.9, recall_interval: [0.6, 0.98],
                hallucination_rate: 0.08, hallucination_interval: [0.02, 0.2],
            },
        ],
    },
};

describe("Bench", () => {
    it("says how to start the first run, and what it would cost to run", async () => {
        stubFetch({ "/api/bench": EMPTY, "/api/jobs": { items: [] } });
        render(Bench);
        expect(await screen.findByText("No benchmark runs yet")).toBeInTheDocument();
        expect(screen.getByText(/2 cases would run/)).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Run benchmark" })).toBeInTheDocument();
    });

    it("renders the readout table, distinguishing a measured row from an unmeasured one", async () => {
        stubFetch({ "/api/bench": ONE_MEASURED, "/api/jobs": { items: [] } });
        render(Bench);
        expect(await screen.findByRole("rowheader", { name: "model-a" })).toBeInTheDocument();
        expect(screen.getAllByText("8.0%").length).toBeGreaterThan(0);
        expect(screen.getByRole("rowheader", { name: "model-b" })).toBeInTheDocument();
        expect(screen.getByText("not yet measured")).toBeInTheDocument();
        expect(
            screen.getByText("fewer than 2 runs measured for this model"),
        ).toBeInTheDocument();
    });

    it("charts a model with a graded, priced protocol", async () => {
        stubFetch({ "/api/bench": ONE_MEASURED, "/api/jobs": { items: [] } });
        render(Bench);
        expect(
            await screen.findByRole("img", { name: /model-a: cost per accepted claim/ }),
        ).toBeInTheDocument();
    });

    it("starts a run and points the reader at Activity to watch it", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async (path: string, init?: RequestInit) => {
                if (init?.method === "POST" && String(path) === "/api/bench") {
                    return new Response(JSON.stringify({ job_id: "j1", kind: "bench" }));
                }
                if (String(path).startsWith("/api/jobs/j1")) {
                    return new Response(JSON.stringify({
                        job_id: "j1", kind: "bench", params: {}, state: "running",
                        progress: 0, message: "", log: "", result: null, done: false,
                        created_at: "", started_at: null, finished_at: null,
                    }));
                }
                if (String(path).startsWith("/api/jobs")) {
                    return new Response(JSON.stringify({ items: [] }));
                }
                if (String(path) === "/api/bench") {
                    return new Response(JSON.stringify(EMPTY));
                }
                return new Response("not stubbed", { status: 500 });
            }),
        );
        render(Bench);
        await fireEvent.click(await screen.findByRole("button", { name: "Run benchmark" }));
        expect(await screen.findByText(/watch it on Activity/)).toBeInTheDocument();
    });

    it("fails with a cause a reader can act on", async () => {
        stubFetchFailing(500);
        render(Bench);
        expect(await screen.findByRole("alert")).toBeInTheDocument();
    });
});
