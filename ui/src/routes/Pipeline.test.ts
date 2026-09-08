import { render, screen, waitFor } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Pipeline from "./Pipeline.svelte";
import { runProgress, stageCount } from "../lib/pipeline";

/* The pipeline view exists to answer a question a job log cannot: did this run
 * find nothing, or find plenty and lose it at the grounding check? So these
 * tests are mostly about *distinctions* — skipped from failed, uncounted
 * tokens from zero tokens, a refusal from a line of noise. A view that blurs
 * any of them is back to being a terminal that "is not functioning". */

const STAGES = [
    { stage: "discovery", label: "Discovery", seq: 0, state: "done", detail: "2 source(s)", items: 2, started_at: "2026-09-08T10:00:00+00:00", ended_at: "2026-09-08T10:00:04+00:00" },
    { stage: "extraction", label: "Extraction", seq: 1, state: "running", detail: "reading 2 source(s)", items: 1, started_at: "2026-09-08T10:00:04+00:00", ended_at: null },
    { stage: "ingestion", label: "Ingestion", seq: 2, state: "waiting", detail: "", items: 0, started_at: null, ended_at: null },
    { stage: "ledgering", label: "Ledgering", seq: 3, state: "waiting", detail: "", items: 0, started_at: null, ended_at: null },
];

const RUN = {
    run_id: "r1",
    job_id: "j1",
    kind: "research",
    subject_id: "s1",
    subject: "Probe Thing",
    pack_id: "probe",
    plane: "agent",
    state: "running",
    sources: 2,
    findings: 3,
    accepted: 1,
    refused: 2,
    chars: 4000,
    tokens: null,
    tokens_counted: false,
    started_at: "2026-09-08T10:00:00+00:00",
    ended_at: null,
    error: null,
};

const EVENTS = [
    { event_id: 1, run_id: "r1", stage: "discovery", at: "2026-09-08T10:00:01+00:00", level: "info", message: "query: probe thing problems", source_url: "", detail: {} },
    { event_id: 2, run_id: "r1", stage: "ingestion", at: "2026-09-08T10:00:09+00:00", level: "refused", message: "refused “DPF blocks”: no quote in the source", source_url: "https://www.example.test/thread/1", detail: {} },
];

// jsdom has no EventSource, so these exercise the polling fallback — which is
// the path that has to work anyway when a stream dies mid-run.
function stub(handlers: Record<string, unknown>) {
    const fetchMock = vi.fn(async (path: string) => {
        const match = Object.keys(handlers)
            .filter((key) => String(path).startsWith(key))
            .sort((a, b) => b.length - a.length)[0];
        if (!match) throw new Error(`unstubbed ${path}`);
        const body = handlers[match];
        return new Response(
            JSON.stringify(typeof body === "function" ? (body as (p: string) => unknown)(path) : body),
        );
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
}

const frame = (over: Record<string, unknown> = {}) => ({
    run: RUN,
    stages: STAGES,
    events: EVENTS,
    cursor: 2,
    live: true,
    ...over,
});

describe("Pipeline", () => {
    it("shows all four stages from the first frame, including the ones not started", async () => {
        // Four boxes that appear one at a time read as a UI loading. Four
        // that fill in read as a pipeline making progress.
        stub({
            "/api/pipeline/runs/": frame(),
            "/api/pipeline/runs": { runs: [RUN], stages: [] },
        });
        render(Pipeline);
        await waitFor(() => screen.getByText("Discovery"));
        for (const label of ["Discovery", "Extraction", "Ingestion", "Ledgering"]) {
            expect(screen.getByText(label)).toBeTruthy();
        }
        expect(screen.getAllByText("waiting").length).toBe(2);
    });

    it("says a run is not metered rather than showing it as free", async () => {
        // The agent plane's marginal cost really is zero and the API plane's
        // is really measured. Rendering an uncounted run as "0 tokens" is a
        // measurement we do not have.
        stub({
            "/api/pipeline/runs/": frame(),
            "/api/pipeline/runs": { runs: [RUN], stages: [] },
        });
        render(Pipeline);
        await waitFor(() => screen.getByText(/not metered on this plane/));
    });

    it("shows a counted run's tokens", async () => {
        stub({
            "/api/pipeline/runs/": frame({
                run: { ...RUN, tokens: 12345, tokens_counted: true },
            }),
            "/api/pipeline/runs": { runs: [RUN], stages: [] },
        });
        render(Pipeline);
        await waitFor(() => screen.getByText(/12,345 tokens/));
    });

    it("names the refusal and the source it came from", async () => {
        // The refusals are the point of the ledger. A view that shows only
        // what was kept cannot explain a run that kept nothing.
        stub({
            "/api/pipeline/runs/": frame(),
            "/api/pipeline/runs": { runs: [RUN], stages: [] },
        });
        render(Pipeline);
        await waitFor(() => screen.getByText(/no quote in the source/));
        // Host, not the whole URL: a monospace log full of query strings is a
        // log nobody reads.
        expect(screen.getByText("example.test")).toBeTruthy();
    });

    it("explains an interrupted run as the app stopping, not as a failure", async () => {
        stub({
            "/api/pipeline/runs/": frame({
                run: {
                    ...RUN,
                    state: "interrupted",
                    error: "the app stopped while this run was going",
                },
                live: false,
            }),
            "/api/pipeline/runs": { runs: [RUN], stages: [] },
        });
        render(Pipeline);
        await waitFor(() => screen.getByText(/cut short when the app stopped/));
    });

    it("says the pipeline has never run rather than showing an empty frame", async () => {
        stub({ "/api/pipeline/runs": { runs: [], stages: [] } });
        render(Pipeline);
        await waitFor(() => screen.getByText(/has not run yet/));
    });

    it("lets a keyboard pick which run to read", async () => {
        // A row that only answers a mouse is a row a keyboard cannot reach,
        // and this is the control that chooses what the whole screen shows.
        stub({
            "/api/pipeline/runs/": frame(),
            "/api/pipeline/runs": { runs: [RUN], stages: [] },
        });
        render(Pipeline);
        await waitFor(() => screen.getAllByRole("button", { name: "Probe Thing" }));
    });

    it("gives the live log its own scroll region, reachable by keyboard", async () => {
        // Not the page's scroll: a log that lengthens the document pushes the
        // stage rail off the top of the screen exactly when it is being read.
        stub({
            "/api/pipeline/runs/": frame(),
            "/api/pipeline/runs": { runs: [RUN], stages: [] },
        });
        render(Pipeline);
        const log = await waitFor(() => screen.getByRole("log"));
        expect(log.getAttribute("tabindex")).toBe("0");
    });
});

describe("pipeline helpers", () => {
    it("counts progress in settled stages, so the bar cannot move backwards", () => {
        // Nothing knows how many findings a source will yield, so a
        // percentage interpolated from item counts goes backwards — and a bar
        // that goes backwards is worse than a coarse one.
        expect(runProgress(STAGES as never)).toBeCloseTo(0.25);
        expect(
            runProgress(STAGES.map((s) => ({ ...s, state: "skipped" })) as never),
        ).toBe(1);
    });

    it("counts each stage in the unit that stage actually produces", () => {
        // "Items: 2" tells the reader nothing about which two things.
        const [discovery, extraction, , ledgering] = STAGES as never[];
        expect(stageCount(discovery, RUN)).toBe("2 sources");
        expect(stageCount(extraction, RUN)).toBe("3 findings");
        expect(stageCount(STAGES[2] as never, RUN)).toBe("");
        expect(stageCount({ ...(ledgering as object), state: "done", items: 3 } as never, RUN)).toBe(
            "3 lines",
        );
    });
});
