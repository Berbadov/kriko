import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Queue from "./Queue.svelte";

/* B193: the Queue screen. The reader picks any number of subjects, one
 * POST /api/research per subject goes out in the order picked, and each
 * row reports its job's state. jsdom has no EventSource, so `follow`
 * takes its polling path, which is the path that has to work anyway. */

const SUBJECT = {
    subject_id: "s-1",
    label: "Bosch GSB 18V-55",
    kind: "product",
    pack_id: "drills",
    claims: 4,
};
const OTHER = {
    subject_id: "s-2",
    label: "Makita DHP484",
    kind: "product",
    pack_id: "drills",
    claims: 0,
};
const JOB = {
    job_id: "j1",
    kind: "research",
    params: { subject_id: "s-1" },
    state: "queued",
    progress: 0,
    message: "",
    log: "",
    result: null,
    done: false,
    created_at: "2026-10-01T10:00:00+00:00",
    started_at: null,
    finished_at: null,
    attention: null,
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

describe("Queue: picking", () => {
    it("searches the catalogs and picks subjects into an ordered queue", async () => {
        const fetchMock = stub({
            "/api/subjects": [SUBJECT, OTHER],
        });
        render(Queue);
        const field = screen.getByRole("textbox");
        await fireEvent.input(field, { target: { value: "drill" } });
        await waitFor(() =>
            expect(
                fetchMock.mock.calls.some(([path]) =>
                    String(path).includes("/api/subjects?limit=25"),
                ),
            ).toBe(true),
        );
        await screen.findByText("Bosch GSB 18V-55");
        expect(screen.getByText("4 claims")).toBeInTheDocument();
    });
});

describe("Queue: submitting", () => {
    it("posts one research job per subject, in the order picked", async () => {
        const fetchMock = stub({
            "/api/subjects": [SUBJECT, OTHER],
            "/api/research": { job_id: "j1", kind: "research" },
            "/api/jobs/j1": JOB,
        });
        render(Queue);
        const field = screen.getByRole("textbox");
        await fireEvent.input(field, { target: { value: "drill" } });
        const first = await screen.findByText("Bosch GSB 18V-55");
        await fireEvent.click(first);
        await fireEvent.input(field, { target: { value: "drill" } });
        const second = await screen.findByText("Makita DHP484");
        await fireEvent.click(second);
        const button = screen.getByRole("button", { name: "Queue 2 products" });
        await fireEvent.click(button);
        await waitFor(() => {
            const calls = fetchMock.mock.calls
                .filter(([path]) => String(path).includes("/api/research"))
                .map(([, init]) => JSON.parse(String(init?.body)));
            expect(calls).toEqual([
                { subject_id: "s-1", pack_id: "drills" },
                { subject_id: "s-2", pack_id: "drills" },
            ]);
        });
    });

    it("shows each job's state and says when the queue has finished", async () => {
        let poll = 0;
        stub({
            "/api/subjects": [SUBJECT],
            "/api/research": { job_id: "j1", kind: "research" },
            "/api/jobs/j1": () =>
                (poll += 1) < 2
                    ? JOB
                    : { ...JOB, state: "succeeded", done: true },
        });
        render(Queue);
        await fireEvent.input(screen.getByRole("textbox"), {
            target: { value: "drill" },
        });
        await fireEvent.click(await screen.findByText("Bosch GSB 18V-55"));
        await fireEvent.click(screen.getByRole("button", { name: "Queue 1 product" }));
        const stage = await screen.findByRole("region", { name: "Queued research" });
        expect(within(stage).getByText(/waiting its turn/)).toBeInTheDocument();
        await waitFor(() =>
            expect(within(stage).getByText(/done/)).toBeInTheDocument(),
        );
        expect(
            within(stage).getByText(/The queue has finished/),
        ).toBeInTheDocument();
    });
});
