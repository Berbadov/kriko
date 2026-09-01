import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Jobs from "./Jobs.svelte";

const JOB = {
    job_id: "j1",
    kind: "research",
    params: { subject_id: "s1" },
    state: "running",
    progress: 0.4,
    message: "reading forum thread",
    log: "query: probe thing problems\n",
    result: null,
    done: false,
    created_at: "2026-09-01T10:00:00+00:00",
    started_at: "2026-09-01T10:00:01+00:00",
    finished_at: null,
};

// jsdom has no EventSource, so these tests exercise the polling fallback —
// which is the path that has to work anyway when a stream dies mid-job.
function stub(handlers: Record<string, unknown>) {
    const fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
        const match = Object.keys(handlers)
            .filter((key) => String(path).startsWith(key))
            .sort((a, b) => b.length - a.length)[0];
        if (!match) throw new Error(`unstubbed ${path}`);
        const body = handlers[match];
        return new Response(
            JSON.stringify(typeof body === "function" ? body(path, init) : body),
        );
    });
    vi.stubGlobal("fetch", fetchMock);
    return fetchMock;
}

describe("Jobs", () => {
    it("shows a running job with its progress and message", async () => {
        // The per-job stub matters: without it the fallback poll would fall
        // through to the list route and the row would be appended twice.
        stub({ "/api/jobs": { items: [JOB] }, "/api/jobs/j1": JOB });
        render(Jobs);
        expect(await screen.findByText(/reading forum thread/)).toBeInTheDocument();
        expect(await screen.findByText("running")).toBeInTheDocument();
        expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "40");
    });

    it("says so when there is nothing to show", async () => {
        stub({ "/api/jobs": { items: [] } });
        render(Jobs);
        expect(await screen.findByText(/No jobs yet/)).toBeInTheDocument();
    });

    it("reveals the log on demand, because a job that failed owes an explanation", async () => {
        stub({
            "/api/jobs": {
                items: [
                    {
                        ...JOB,
                        state: "failed",
                        done: true,
                        message: "KeyError: no subject nope",
                        log: "Traceback (most recent call last):\n",
                    },
                ],
            },
        });
        render(Jobs);
        await fireEvent.click(await screen.findByRole("button", { name: "Log" }));
        expect(await screen.findByText(/Traceback/)).toBeInTheDocument();
    });

    it("names an interrupted job as a restart rather than a mystery", async () => {
        stub({ "/api/jobs": { items: [{ ...JOB, state: "interrupted", done: true }] } });
        render(Jobs);
        expect(await screen.findByText(/interrupted by a restart/)).toBeInTheDocument();
    });

    it("starts a build from the directory field", async () => {
        const fetchMock = stub({
            "/api/jobs": { items: [] },
            "/api/jobs/j2": { ...JOB, job_id: "j2", kind: "pack_build", done: true, state: "succeeded" },
            "/api/packs/build": { job_id: "j2", kind: "pack_build" },
        });
        render(Jobs);
        await screen.findByText(/No jobs yet/);
        await fireEvent.input(screen.getByLabelText("Build a pack from a directory"), {
            target: { value: "packs/drill" },
        });
        await fireEvent.click(screen.getByRole("button", { name: "Build and install" }));
        await waitFor(() =>
            expect(
                fetchMock.mock.calls.some(([path]) =>
                    String(path).includes("/api/packs/build"),
                ),
            ).toBe(true),
        );
        expect(await screen.findByText("done")).toBeInTheDocument();
    });
});
