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
    it("disables cancellation while the worker is stopping", async () => {
        const job = { ...JOB, state: "cancelling", cancel_requested: true };
        const fetchMock = stub({ "/api/jobs": { items: [job] }, "/api/jobs/j1": job });
        render(Jobs);
        const button = await screen.findByRole("button", { name: "Stopping…" });
        expect(button).toBeDisabled();
        await fireEvent.click(button);
        expect(fetchMock.mock.calls.some(([path]) => path.endsWith("/cancel"))).toBe(false);
        expect(screen.getByRole("progressbar")).toBeInTheDocument();
    });

    it("keeps Cancel disabled until the cancellation request completes", async () => {
        let release!: (response: Response) => void;
        const fetchMock = vi.fn((path: string) => {
            if (path.endsWith("/cancel")) return new Promise<Response>((resolve) => { release = resolve; });
            return Promise.resolve(new Response(JSON.stringify(
                path.split("?")[0] === "/api/jobs" ? { items: [JOB] } : JOB,
            )));
        });
        vi.stubGlobal("fetch", fetchMock);
        render(Jobs);
        await fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));
        expect(screen.getByRole("button", { name: "Stopping…" })).toBeDisabled();
        expect(fetchMock.mock.calls.filter(([path]) => path.endsWith("/cancel"))).toHaveLength(1);
        release(new Response(JSON.stringify({ state: "cancelling" })));
        await waitFor(() => expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled());
    });

    it("shows a running job with its progress and message", async () => {
        // The per-job stub matters: without it the fallback poll would fall
        // through to the list route and the row would be appended twice.
        stub({ "/api/jobs": { items: [JOB] }, "/api/jobs/j1": JOB });
        render(Jobs);
        expect(await screen.findByText(/reading forum thread/)).toBeInTheDocument();
        expect(await screen.findByText("running")).toBeInTheDocument();
        expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "40");
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
        await screen.findByText("No runs yet");
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

    it("offers a failed job another attempt without losing why it failed", async () => {
        const failed = {
            ...JOB,
            state: "failed",
            done: true,
            message: "the source timed out",
            finished_at: "2026-09-01T10:05:00+00:00",
        };
        const fetchMock = stub({
            "/api/jobs": { items: [failed] },
            "/api/jobs/j1": failed,
            "/api/jobs/j1/retry": { job_id: "j2", kind: "research" },
            "/api/jobs/j2": { ...JOB, job_id: "j2", params: { subject_id: "s1", retry_of: "j1" } },
        });
        render(Jobs);
        await fireEvent.click(await screen.findByRole("button", { name: "Run again" }));
        await waitFor(() =>
            expect(
                fetchMock.mock.calls.some(([path]) =>
                    String(path).includes("/api/jobs/j1/retry"),
                ),
            ).toBe(true),
        );
        // The failed row stays, with its reason: a retry is a second attempt,
        // not a correction of the first.
        expect(screen.getByText("the source timed out")).toBeInTheDocument();
    });

    it("disables Run again while the retry request is in flight", async () => {
        // ops-5: `retry` had no pending guard, so a double-click sent two
        // `POST /retry` before the first had come back.
        const failed = {
            ...JOB, state: "failed", done: true,
            message: "the source timed out",
            finished_at: "2026-09-01T10:05:00+00:00",
        };
        let release!: (response: Response) => void;
        const fetchMock = vi.fn((path: string) => {
            if (path.endsWith("/retry")) {
                return new Promise<Response>((resolve) => { release = resolve; });
            }
            return Promise.resolve(new Response(JSON.stringify(
                path.split("?")[0] === "/api/jobs" ? { items: [failed] } : failed,
            )));
        });
        vi.stubGlobal("fetch", fetchMock);
        render(Jobs);
        const button = await screen.findByRole("button", { name: "Run again" });
        await fireEvent.click(button);
        await waitFor(() => expect(screen.getByRole("button", { name: "Starting…" })).toBeDisabled());
        await fireEvent.click(screen.getByRole("button", { name: "Starting…" }));
        expect(fetchMock.mock.calls.filter(([path]) => String(path).endsWith("/retry")).length).toBe(1);
        release(new Response(JSON.stringify({ job_id: "j2", kind: "research" })));
    });

    it("does not offer to re-run a job that is still going", async () => {
        stub({ "/api/jobs": { items: [JOB] }, "/api/jobs/j1": JOB });
        render(Jobs);
        await screen.findByText("reading forum thread");
        expect(screen.queryByRole("button", { name: "Run again" })).toBeNull();
        expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    });

    it("starts a whole pack from a category and one press", async () => {
        const fetchMock = stub({
            "/api/jobs": { items: [] },
            "/api/packs/author": { job_id: "j3", kind: "pack_author" },
            "/api/jobs/j3": {
                ...JOB,
                job_id: "j3",
                kind: "pack_author",
                params: { category: "cordless drills" },
                state: "running",
                done: false,
                message: "Claude Code is reading up on cordless drills",
            },
        });
        render(Jobs);
        await screen.findByText("No runs yet");
        await fireEvent.click(screen.getByText("Start a new pack"));
        await fireEvent.input(screen.getByLabelText("What is the category?"), {
            target: { value: "cordless drills" },
        });
        await fireEvent.click(
            screen.getByRole("button", { name: "Have my agent write it" }),
        );
        await waitFor(() => {
            const call = fetchMock.mock.calls.find(([path]) =>
                String(path).includes("/api/packs/author"),
            );
            expect(call).toBeTruthy();
            // One field on the wire. Everything the old form asked for — an
            // id, a name, an identity table — is category knowledge the agent
            // decides, and a reader who has not read the category cannot.
            expect(JSON.parse(String(call![1]?.body))).toEqual({
                category: "cordless drills",
            });
        });
        // The row is on screen and named as what it is, not as a build: this
        // run installs nothing.
        expect(await screen.findByText("New pack")).toBeInTheDocument();
        expect(screen.getByText("cordless drills")).toBeInTheDocument();
        expect(
            await screen.findByText(/reading up on cordless drills/),
        ).toBeInTheDocument();
    });

    it("will not start an agent with no category to read about", async () => {
        stub({ "/api/jobs": { items: [] } });
        render(Jobs);
        await fireEvent.click(await screen.findByText("Start a new pack"));
        // The one thing the reader does have to say. The handler refuses it
        // too, but a press that starts a job in order to fail it is worse
        // than a button that waits.
        expect(
            screen.getByRole("button", { name: "Have my agent write it" }),
        ).toBeDisabled();
    });

    // B146: "im unable to see the options for resource and effort limit".
    it("shows agent, effort and a time limit beside the new-pack button, and sends them", async () => {
        const saved: Record<string, string>[] = [];
        const fetchMock = stub({
            "/api/jobs": { items: [] },
            "/api/prefs": (_path: string, init?: RequestInit) => {
                if (init?.method === "PUT") saved.push(JSON.parse(String(init.body)));
                return {
                    chosen: { preferred_harness: "", llm_model: "", search_provider: "" },
                    harnesses: [
                        { id: "claude-code", label: "Claude Code", command: "claude",
                          llm: "", llms: ["sonnet"], llm_selectable: true,
                          effort: "", efforts: ["low", "high"] },
                        { id: "codex", label: "Codex", command: "codex", efforts: [] },
                    ],
                    unusable: [], missing: [],
                };
            },
            "/api/packs/author": { job_id: "j9", kind: "pack_author" },
            "/api/jobs/j9": { ...JOB, job_id: "j9", kind: "pack_author" },
        });
        render(Jobs);
        // Visible without opening anything.
        const agent = await screen.findByLabelText(/Agent/);
        await fireEvent.change(screen.getByLabelText(/Effort/), { target: { value: "low" } });
        await waitFor(() => expect(saved).toContainEqual({ harness_effort_claude_code: "low" }));
        await fireEvent.change(agent, { target: { value: "codex" } });
        // Codex declares no effort dial, so none is drawn for it.
        expect(screen.queryByLabelText(/Effort/)).toBeNull();
        await fireEvent.change(screen.getByLabelText(/Stop after/), { target: { value: "600" } });
        await fireEvent.input(screen.getByLabelText("What is the category?"), {
            target: { value: "e-bikes" },
        });
        await fireEvent.click(screen.getByRole("button", { name: "Have my agent write it" }));
        await waitFor(() => {
            const call = fetchMock.mock.calls.find(([path]) => String(path).includes("/api/packs/author"));
            expect(JSON.parse(String(call![1]?.body))).toEqual({
                category: "e-bikes", harness: "codex", timeout_seconds: 600,
            });
        });
    });

    it("shows how long a live run has been going and its latest log line", async () => {
        const started = new Date(Date.now() - 372_000).toISOString();
        const job = { ...JOB, started_at: started, log: "query: a\nstill working — 6m 12s in\n" };
        stub({ "/api/jobs": { items: [job] }, "/api/jobs/j1": job });
        render(Jobs);
        expect(await screen.findByText(/^6m 1\ds$/)).toBeInTheDocument();
        expect(screen.getByText("still working — 6m 12s in")).toBeInTheDocument();
    });

    it("explains an empty run list, and points at where runs come from", async () => {
        stub({ "/api/jobs": { items: [] } });
        render(Jobs);
        expect(await screen.findByText("No runs yet")).toBeInTheDocument();
        // The gap screen is where the other door into this list is, so the
        // empty state names it instead of leaving the reader on a form.
        const link = screen.getByRole("link", { name: "Find a gap" }) as HTMLAnchorElement;
        expect(link.getAttribute("href")).toBe("#/knowledge");
    });

    // ── answering a run that is still going ──────────────────────────────

    it("offers a reply box on a live run and posts what was typed", async () => {
        const fetchMock = stub({
            "/api/jobs": { items: [JOB] },
            "/api/jobs/j1": JOB,
            "/api/jobs/j1/say": { job_id: "j1", delivered: true },
        });
        render(Jobs);

        const box = await screen.findByLabelText("Reply to this run");
        await fireEvent.input(box, { target: { value: "the second one" } });
        await fireEvent.click(screen.getByRole("button", { name: "Send" }));

        await waitFor(() => {
            const call = fetchMock.mock.calls.find(([path]) => String(path).endsWith("/say"));
            expect(call).toBeTruthy();
            expect(JSON.parse(String(call![1]!.body))).toEqual({ text: "the second one" });
        });
        // Emptied, because the next thing the reader types is a second reply
        // and not an edit of the first.
        await waitFor(() => expect((box as HTMLInputElement).value).toBe(""));
        expect(await screen.findByText("Sent.")).toBeInTheDocument();
    });

    it("does not offer a reply box on a run that is over", async () => {
        const done = { ...JOB, state: "succeeded", done: true, finished_at: "2026-09-01T10:05:00+00:00" };
        stub({ "/api/jobs": { items: [done] }, "/api/jobs/j1": done });
        render(Jobs);

        await screen.findByText(/research/);
        expect(screen.queryByLabelText("Reply to this run")).toBeNull();
    });

    it("says so when the run ended while the reader was typing", async () => {
        // `delivered: false` rather than an error, so the panel has to say
        // the words itself — silence here reads as "sent".
        stub({
            "/api/jobs": { items: [JOB] },
            "/api/jobs/j1": JOB,
            "/api/jobs/j1/say": { job_id: "j1", delivered: false },
        });
        render(Jobs);

        const box = await screen.findByLabelText("Reply to this run");
        await fireEvent.input(box, { target: { value: "too late" } });
        await fireEvent.click(screen.getByRole("button", { name: "Send" }));

        expect(await screen.findByText(/Nothing was sent/)).toBeInTheDocument();
    });
});

describe("noticing runs started elsewhere", () => {
    it("picks up a job that appears in the list after mount, without a reload", async () => {
        // B145 ops-8: the list was only ever read once, on mount, so a run
        // started from Packs, an agent, or the API stayed invisible here
        // until the reader reloaded the screen.
        vi.useFakeTimers();
        let call = 0;
        const fetchMock = vi.fn(async (path: string) => {
            if (String(path).startsWith("/api/jobs/j2")) {
                return new Response(JSON.stringify({
                    ...JOB, job_id: "j2", message: "started elsewhere",
                }));
            }
            if (String(path).startsWith("/api/jobs")) {
                call += 1;
                const items =
                    call === 1 ? [] : [{ ...JOB, job_id: "j2", message: "started elsewhere" }];
                return new Response(JSON.stringify({ items }));
            }
            throw new Error(`unstubbed ${path}`);
        });
        vi.stubGlobal("fetch", fetchMock);
        render(Jobs);
        await screen.findByText("No runs yet");
        await vi.advanceTimersByTimeAsync(4000);
        expect(await screen.findByText(/started elsewhere/)).toBeInTheDocument();
        vi.useRealTimers();
    });
});

describe("a run that asked something (B147)", () => {
    const QUESTION = {
        id: "engine_code",
        ask: "Which engine code is it?",
        key: "",
        options: ["BUG", "CASA"],
        default: "BUG",
        because: "BUG was the common one that year.",
    };
    const ATTENTION = { kind: "questions", count: 1, say: "", questions: [QUESTION] };
    const RESULT = { questions: [QUESTION], why: "two codes overlap", stopped_at: "disambiguation" };

    it("says a picked answer to a live run at once, and shows it landed", async () => {
        const job = { ...JOB, kind: "pack_author", result: RESULT, attention: ATTENTION };
        const fetchMock = stub({
            "/api/jobs": { items: [job] },
            "/api/jobs/j1": job,
            "/api/jobs/j1/say": { job_id: "j1", delivered: true },
        });
        render(Jobs);
        await fireEvent.click(await screen.findByRole("radio", { name: "CASA" }));
        expect(await screen.findByText("It heard you.")).toBeInTheDocument();
        const said = fetchMock.mock.calls.find(([path]) => String(path).endsWith("/say"));
        expect(JSON.parse(String(said?.[1]?.body)).text).toContain("CASA");
        expect(screen.getByRole("radio", { name: "CASA" })).toHaveAttribute("aria-checked", "true");
        // No retry offered on a run that is still going: it already heard.
        expect(screen.queryByRole("button", { name: "Answer and run again" })).toBeNull();
    });

    it("never shows the question as raw JSON in the log", async () => {
        const job = { ...JOB, state: "interrupted", done: true, result: RESULT, attention: ATTENTION };
        stub({ "/api/jobs": { items: [job] }, "/api/jobs/j1": job });
        render(Jobs);
        await fireEvent.click(await screen.findByRole("button", { name: "Log" }));
        expect(screen.queryByText(/"stopped_at"/)).toBeNull();
        expect(screen.getByRole("radio", { name: /BUG/ })).toBeInTheDocument();
    });

    it("carries a picked answer on a finished run into the retry", async () => {
        const job = { ...JOB, state: "interrupted", done: true, result: RESULT, attention: ATTENTION };
        const fetchMock = stub({
            "/api/jobs": { items: [job] },
            "/api/jobs/j1": job,
            "/api/jobs/j1/retry": { job_id: "j9", kind: "pack_author" },
            "/api/jobs/j9": { ...job, job_id: "j9", state: "queued", done: false, attention: null },
        });
        render(Jobs);
        await fireEvent.click(await screen.findByRole("radio", { name: "CASA" }));
        expect(fetchMock.mock.calls.some(([path]) => String(path).endsWith("/say"))).toBe(false);
        await fireEvent.click(screen.getByRole("button", { name: "Answer and run again" }));
        await waitFor(() => {
            const retried = fetchMock.mock.calls.find(([path]) => String(path).endsWith("/retry"));
            expect(JSON.parse(String(retried?.[1]?.body)).answers).toEqual({ engine_code: "CASA" });
        });
    });
});
