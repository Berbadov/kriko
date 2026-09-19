import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
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

const WITH_OPTIONS: BenchPayload = {
    ...EMPTY,
    cases: [
        { subject_id: "c1", pack_id: "probe", label: "Thing one" },
        { subject_id: "c2", pack_id: "probe", label: "Thing two" },
    ],
    protocols: [
        { name: "standard", context_chars: 12000, batch_size: 1, preamble: "" },
        { name: "wide", context_chars: 10000, batch_size: 4, preamble: "" },
    ],
};

const PREFS = {
    models: {
        offered: [
            { id: "model-a", label: "Model A", provider: "openai", unusable: "" },
            { id: "model-b", label: "Model B", provider: "anthropic", unusable: "" },
        ],
    },
    search_providers: [
        { id: "exa", label: "Exa", ready: true },
        { id: "tavily", label: "Tavily", ready: true },
    ],
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

    it("renders every sweep axis as a choice control with no free typing", async () => {
        stubFetch({
            "/api/bench": WITH_OPTIONS,
            "/api/prefs": PREFS,
            "/api/jobs": { items: [] },
            "/api/bench/configs": { configs: {} },
        });
        render(Bench);
        for (const plane of ["harness", "agent", "api"]) {
            expect(await screen.findByRole("button", { name: plane })).toBeInTheDocument();
        }
        for (const scale of ["Quick", "Standard", "Deep"]) {
            expect(screen.getByRole("button", { name: scale })).toBeInTheDocument();
        }
        expect(screen.getByRole("button", { name: "Model A" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Model B" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Exa" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Tavily" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "standard" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "wide" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Fewer repetitions" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "More repetitions" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Lower ceiling" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Raise ceiling" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Fewer cases" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "More cases" })).toBeInTheDocument();
        expect(screen.getByRole("combobox", { name: "Pack" })).toBeInTheDocument();
        expect(screen.queryByRole("spinbutton")).toBeNull();
        const textboxes = screen.queryAllByRole("textbox");
        expect(textboxes).toHaveLength(1);
    });

    it("sends exactly the selections when estimating", async () => {
        const seen: { path: string; body: Record<string, unknown> }[] = [];
        vi.stubGlobal(
            "fetch",
            vi.fn(async (path: string, init?: RequestInit) => {
                if (init?.method === "POST" && String(path) === "/api/bench/estimate") {
                    seen.push({ path: String(path), body: JSON.parse(String(init.body)) });
                    return new Response(JSON.stringify({
                        runs: 96, usd: 0.5, tokens: 1000, basis: 3,
                        note: "estimated from 3 measured run(s) here",
                        axes: { cases: 4, planes: 2, protocols: 1, searches: 1, models: 2, reps: 2 },
                    }));
                }
                if (String(path).startsWith("/api/prefs")) {
                    return new Response(JSON.stringify(PREFS));
                }
                if (String(path).startsWith("/api/bench/configs")) {
                    return new Response(JSON.stringify({ configs: {} }));
                }
                if (String(path).startsWith("/api/jobs")) {
                    return new Response(JSON.stringify({ items: [] }));
                }
                if (String(path) === "/api/bench") {
                    return new Response(JSON.stringify(WITH_OPTIONS));
                }
                return new Response("not stubbed", { status: 500 });
            }),
        );
        render(Bench);
        await fireEvent.click(await screen.findByRole("button", { name: "agent" }));
        await fireEvent.click(await screen.findByRole("button", { name: "Model A" }));
        await fireEvent.click(await screen.findByRole("button", { name: "Model B" }));
        await fireEvent.click(await screen.findByRole("button", { name: "Tavily" }));
        await fireEvent.click(await screen.findByRole("button", { name: "wide" }));
        await fireEvent.click(await screen.findByRole("button", { name: "Deep" }));
        await fireEvent.click(await screen.findByRole("button", { name: "More repetitions" }));
        await fireEvent.click(await screen.findByRole("button", { name: "More cases" }));
        await fireEvent.click(await screen.findByRole("button", { name: "Raise ceiling" }));
        await fireEvent.click(await screen.findByRole("button", { name: "Estimate" }));
        await waitFor(() => expect(seen.length).toBeGreaterThan(0));
        const last = seen[seen.length - 1].body;
        expect(last["planes"]).toBe("harness, agent");
        expect(last["llms"]).toBe("model-a, model-b");
        expect(last["searches"]).toBe("tavily");
        expect(last["protocols"]).toBe("wide");
        expect(last["cases"]).toBe(4);
        expect(last["reps"]).toBe(2);
        expect(last["budget_usd"]).toBe(0.25);
        expect(last["max_documents"]).toBe(15);
        expect(await screen.findByText(/96 measurement\(s\)/)).toBeInTheDocument();
    });

    it("loads a saved grid into the choice controls", async () => {
        stubFetch({
            "/api/bench": WITH_OPTIONS,
            "/api/prefs": PREFS,
            "/api/jobs": { items: [] },
            "/api/bench/configs": {
                configs: {
                    evening: {
                        planes: "api", pack_id: "", cases: 2, max_documents: 15,
                        budget_usd: 0.5, protocols: "wide", reps: 2,
                        llms: "model-a", searches: "tavily",
                    },
                },
            },
        });
        render(Bench);
        await fireEvent.click(await screen.findByRole("button", { name: "Load" }));
        await waitFor(() =>
            expect(screen.getByRole("button", { name: "api" })).toHaveAttribute("aria-pressed", "true"),
        );
        expect(screen.getByRole("button", { name: "Deep" })).toHaveAttribute("aria-pressed", "true");
        expect(screen.getByRole("button", { name: "Model A" })).toHaveAttribute("aria-pressed", "true");
        expect(screen.getByRole("button", { name: "Tavily" })).toHaveAttribute("aria-pressed", "true");
        expect(screen.getByRole("button", { name: "wide" })).toHaveAttribute("aria-pressed", "true");
    });
});
