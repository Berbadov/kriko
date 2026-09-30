import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Run from "./Run.svelte";

/* B175 and B176: the Run screen. jsdom has no EventSource, so the job follower
 * takes its polling path, which is the path that has to work anyway when a
 * stream dies mid-run. */

const JOB = {
    job_id: "j1",
    kind: "pack_author",
    params: { category: "e-bikes", harness: "" },
    state: "running",
    progress: 0.3,
    message: "Claude Code is reading up on e-bikes",
    log: "",
    result: null,
    done: false,
    created_at: "2026-09-01T10:00:00+00:00",
    started_at: "2026-09-01T10:00:01+00:00",
    finished_at: null,
    attention: null,
    feed: [
        { kind: "search", text: 'searched "e-bike motor faults"' },
        { kind: "source", text: "fetched https://example.test/a" },
        { kind: "source", text: "fetched https://example.test/b" },
        { kind: "finding", text: "kept “Motor cuts out” as c-1" },
    ],
};

const PREFS = {
    chosen: { preferred_harness: "", llm_model: "", search_provider: "" },
    harnesses: [
        { id: "claude-code", label: "Claude Code", command: "claude", llm: "",
          llms: ["claude-sonnet-x"], llm_selectable: true, effort: "", efforts: ["low", "high"] },
        { id: "opencode", label: "OpenCode", command: "opencode", efforts: [] },
    ],
    unusable: [], missing: [],
};

const SCALES = {
    default: "standard",
    scales: [
        { id: "quick", label: "Quick", note: "", max_documents: 3, context_chars: 0, batch_size: 3,
          usd: 0.06, tokens: null, basis: 1, cap_usd: 0.3 },
        { id: "standard", label: "Standard", note: "", max_documents: 7, context_chars: 0, batch_size: 2,
          usd: 0.14, tokens: null, basis: 1, cap_usd: 1 },
    ],
};

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

const base = (extra: Record<string, unknown> = {}) => ({
    "/api/jobs": { items: [] },
    "/api/prefs": PREFS,
    "/api/scales": SCALES,
    ...extra,
});

describe("Run: the form", () => {
    it("starts from one compact form, with no paragraph under any control", async () => {
        stub(base());
        const { container } = render(Run);
        await screen.findByRole("button", { name: /Agent:/ });
        expect(container.querySelector(".form p")).toBeNull();
        expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();
    });

    it("sends the agent, the time limit and the source count the reader set", async () => {
        const fetchMock = stub(base({
            "/api/packs/author": { job_id: "j9", kind: "pack_author" },
            "/api/jobs/j9": { ...JOB, job_id: "j9" },
        }));
        render(Run);
        const agent = await screen.findByRole("button", { name: /Agent:/ });
        await fireEvent.click(agent);
        await fireEvent.click(await screen.findByRole("option", { name: "OpenCode" }));
        await fireEvent.click(screen.getByRole("button", { name: /Stop after:/ }));
        await fireEvent.click(await screen.findByRole("option", { name: "10 min" }));
        await waitFor(() => expect(screen.getByRole("slider")).toHaveValue("7"));
        await fireEvent.input(screen.getByRole("slider"), { target: { value: "12" } });
        await fireEvent.input(screen.getByLabelText("Category"), { target: { value: "e-bikes" } });
        await fireEvent.click(screen.getByRole("button", { name: "Start" }));
        await waitFor(() => {
            const call = fetchMock.mock.calls.find(([path]) => String(path).includes("/api/packs/author"));
            expect(JSON.parse(String(call![1]?.body))).toEqual({
                category: "e-bikes", harness: "opencode", timeout_seconds: 600, max_documents: 12,
            });
        });
    });
});

describe("Run: the sources slider", () => {
    it("starts at the server's default and shows the count and an estimate", async () => {
        stub(base());
        render(Run);
        const slider = await screen.findByRole("slider");
        await waitFor(() => expect(slider).toHaveValue("7"));
        expect(screen.getByText("~$0.14")).toBeInTheDocument();
        await fireEvent.input(slider, { target: { value: "14" } });
        expect(screen.getByText("14", { selector: "output" })).toBeInTheDocument();
        expect(screen.getByText("~$0.28")).toBeInTheDocument();
    });

    it("has no number field and no preset chips", async () => {
        stub(base());
        render(Run);
        await screen.findByRole("slider");
        expect(screen.queryByRole("spinbutton")).toBeNull();
        expect(screen.queryByRole("button", { name: "Quick" })).toBeNull();
    });

    it("says there is no estimate where nothing has been measured, never zero", async () => {
        stub(base({ "/api/scales": { ...SCALES, scales: SCALES.scales.map((s) => ({ ...s, usd: null })) } }));
        render(Run);
        expect(await screen.findByText("No estimate yet")).toBeInTheDocument();
    });
});

describe("Run: the live panel (B176)", () => {
  it("shows the running agent, what it is doing, and each source and finding", async () => {
        const job = { ...JOB, job_id: "j1" };
        stub(base({ "/api/jobs": { items: [job] }, "/api/jobs/j1": job }));
        render(Run);
        const panel = await screen.findByRole("region", { name: "Claude Code run" });
        // What it is doing now is the newest event, not a status paragraph.
        expect(within(panel).getByText("kept “Motor cuts out” as c-1", { selector: ".doing" })).toBeInTheDocument();
        const log = within(panel).getByRole("log", { name: "What the agent did" });
        expect(within(log).getAllByText(/^fetched /)).toHaveLength(2);
        expect(within(panel).getByText("2", { selector: "b" })).toBeInTheDocument();
        // Without pressing anything called Log.
        expect(screen.queryByRole("button", { name: "Log" })).toBeNull();
    });

    it("lets the reader stop the run from the panel", async () => {
        const job = { ...JOB, job_id: "j1" };
        const fetchMock = stub(base({
            "/api/jobs": { items: [job] },
            "/api/jobs/j1/cancel": { job_id: "j1", state: "cancelling" },
            "/api/jobs/j1": job,
        }));
        render(Run);
        await fireEvent.click(await screen.findByRole("button", { name: "Stop" }));
        await waitFor(() =>
            expect(fetchMock.mock.calls.some(([p, i]) =>
                String(p).endsWith("/api/jobs/j1/cancel") && i?.method === "POST")).toBe(true),
        );
    });

    it("lets the reader answer the run from the panel", async () => {
        const job = { ...JOB, job_id: "j1" };
        const fetchMock = stub(base({
            "/api/jobs": { items: [job] },
            "/api/jobs/j1/say": { job_id: "j1", delivered: true },
            "/api/jobs/j1": job,
        }));
        render(Run);
        const box = await screen.findByLabelText("Reply to this run");
        await fireEvent.input(box, { target: { value: "the 2024 model" } });
        await fireEvent.click(screen.getByRole("button", { name: "Send" }));
        await waitFor(() => {
            const call = fetchMock.mock.calls.find(([p]) => String(p).endsWith("/say"));
            expect(JSON.parse(String(call![1]?.body))).toEqual({ text: "the 2024 model" });
        });
    });

    it("puts a question's options in the panel as presses", async () => {
        const job = {
            ...JOB,
            attention: { kind: "questions", count: 1, say: "",
                questions: [{ id: "q1", ask: "Which year?", key: "", options: ["2023", "2024"],
                              default: "2024", because: "" }] },
        };
        const fetchMock = stub(base({
            "/api/jobs": { items: [job] },
            "/api/jobs/j1/say": { job_id: "j1", delivered: true },
            "/api/jobs/j1": job,
        }));
        render(Run);
        await fireEvent.click(await screen.findByRole("button", { name: "2023" }));
        await waitFor(() => {
            const call = fetchMock.mock.calls.find(([p]) => String(p).endsWith("/say"));
            expect(JSON.parse(String(call![1]?.body)).text).toContain("2023");
        });
    });

    it("says nothing is going when nothing is", async () => {
        stub(base());
        render(Run);
        expect(await screen.findByText("No run is going")).toBeInTheDocument();
    });
});
