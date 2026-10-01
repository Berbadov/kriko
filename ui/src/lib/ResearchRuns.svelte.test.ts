import { render, screen, waitFor } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import ResearchRuns from "./ResearchRuns.svelte";
import { stubFetch, stubFetchFailing } from "./stub-fetch";

const run = (over: Record<string, unknown> = {}) => ({
    run_id: "r1",
    job_id: "j0",
    plane: "api",
    llm: "a-model",
    search_provider: "a-provider",
    budget_usd: 0.2,
    spent_usd: 0.1134,
    tokens_used: null,
    started_at: "2026-09-09T20:15:00",
    ended_at: "2026-09-09T20:16:00",
    outcome: "done",
    claims: 4,
    removed: 0,
    ...over,
});

const runs = (...items: Record<string, unknown>[]) => ({
    "/api/research-runs": { runs: items },
});

describe("the research runs list", () => {
    it("names what wrote the claims rather than saying it was automatic", async () => {
        stubFetch(runs(run()));
        render(ResearchRuns);
        // Provenance a reader can weigh: which plane, which completion API,
        // which search provider. "Researched automatically" is not a record.
        expect(
            await screen.findByText("Kriko itself · a-model via a-provider"),
        ).toBeTruthy();
        expect(await screen.findByText(/spent \$0\.1134/)).toBeTruthy();
        expect(await screen.findByText(/of \$0\.20/)).toBeTruthy();
    });

    it("leaves the cost blank when nobody counted", async () => {
        // The agent plane never counts, and NULL is not zero: showing $0.00
        // would claim a measurement that was never made.
        stubFetch(runs(run({ plane: "agent", spent_usd: null, budget_usd: null })));
        const { container } = render(ResearchRuns);
        expect(await screen.findByText("your agent")).toBeTruthy();
        expect(container.textContent).not.toContain("spent $");
        expect(container.textContent).not.toContain("0.00");
    });

    it("shows the tokens a plane could count, and nothing for one that could not", async () => {
        // Two currencies, not one: the harness plane knows its tokens and
        // spends none of Kriko's money, so a run can have a count and no
        // price. A missing count reads as absent rather than as zero.
        stubFetch(runs(run({ tokens_used: 12345, spent_usd: null })));
        render(ResearchRuns);
        await waitFor(() =>
            expect(screen.getByText(/12,345 tokens/)).toBeInTheDocument(),
        );
        expect(screen.queryByText(/spent \$/)).not.toBeInTheDocument();
    });

    it("says a budget stop was a stop, not a completed run", async () => {
        stubFetch(runs(run({ outcome: "budget" })));
        render(ResearchRuns);
        expect(await screen.findByText("stopped at the budget")).toBeTruthy();
    });

    it("offers an undo while there is something to undo", async () => {
        stubFetch({
            ...runs(run()),
            "/api/research-runs/r1": { job_id: "u1", kind: "research_undo" },
            "/api/jobs/u1": {
                job_id: "u1",
                kind: "research_undo",
                state: "running",
                done: false,
                message: "removing",
                log: "",
                result: null,
                progress: 0.5,
            },
        });
        render(ResearchRuns);
        const button = await screen.findByText("Undo this run");
        button.click();
        await new Promise((resolve) => setTimeout(resolve, 0));

        const calls = (fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls;
        const undo = calls.find(
            (call) =>
                String(call[0]) === "/api/research-runs/r1" &&
                (call[1] as RequestInit)?.method === "DELETE",
        );
        expect(undo).toBeTruthy();
    });

    it("does not offer an undo that would do nothing", async () => {
        // Already undone: four claims written, four taken back out. A button
        // here would queue a job whose whole output is "nothing to remove".
        stubFetch(runs(run({ claims: 0, removed: 4 })));
        render(ResearchRuns);
        expect(await screen.findByText(/4 taken back out/)).toBeTruthy();
        expect(screen.queryByText("Undo this run")).toBeNull();
    });

    it("counts what is still in the store, not what the run once wrote", async () => {
        stubFetch(runs(run({ claims: 1, removed: 3 })));
        render(ResearchRuns);
        expect(await screen.findByText(/1 claim still in/)).toBeTruthy();
    });

    it("points at the planes when nothing has run here yet", async () => {
        stubFetch(runs());
        const { container } = render(ResearchRuns);
        expect(await screen.findByText(/No research has run here yet/)).toBeTruthy();
        expect(container.querySelector('a[href="#/agents"]')).toBeTruthy();
    });

    it("surfaces a failure instead of rendering an empty section", async () => {
        stubFetchFailing();
        render(ResearchRuns);
        expect(await screen.findByText("Research runs")).toBeTruthy();
        expect(await screen.findByRole("button", { name: /again|retry/i })).toBeTruthy();
    });
});
