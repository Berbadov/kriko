import { afterEach, describe, expect, it, vi } from "vitest";

// B145 ops-7: the rail's `running` figure used to wait for its own 30s clock
// to learn that a job had started or finished — `nudge()` existed already
// but nothing called it. Mocking the module lets the assertion be exactly
// "did `follow` ask the rail to re-read", without also depending on what the
// rail's own network calls happen to return in a test environment.
const nudge = vi.fn();
vi.mock("./shell/instruments", () => ({ nudge }));

const { follow } = await import("./jobs");

afterEach(() => {
    nudge.mockClear();
    vi.unstubAllGlobals();
});

/** Stub `/api/job/:id` with one response per call, in order — `follow`'s
 *  poll fallback re-reads the same URL every tick, so a single fixed payload
 *  (as `stubFetch` gives every caller) can never show a job finishing. */
function stubJobSequence(...bodies: unknown[]): void {
    let call = 0;
    vi.stubGlobal(
        "fetch",
        vi.fn(async () => {
            const body = bodies[Math.min(call, bodies.length - 1)];
            call += 1;
            return new Response(JSON.stringify(body));
        }),
    );
}

describe("following a job", () => {
    it("nudges the rail on the first update and again when the job finishes, not on ticks between", async () => {
        stubJobSequence(
            { job_id: "j1", state: "running", done: false, log: "" },
            { job_id: "j1", state: "running", done: false, log: "" },
            { job_id: "j1", state: "succeeded", done: true, log: "" },
        );
        const seen: boolean[] = [];
        const stop = follow("j1", (job) => seen.push(job.done));
        // Three polls: started, unchanged, finished. `follow`'s poll fallback
        // ticks every `POLL_MS` (700ms in real code, but the stub answers
        // instantly so waiting past three ticks is enough).
        await new Promise((r) => setTimeout(r, 0));
        await new Promise((r) => setTimeout(r, 750));
        await new Promise((r) => setTimeout(r, 750));
        stop();
        expect(seen).toEqual([false, false, true]);
        expect(nudge).toHaveBeenCalledTimes(2);
    });
});
