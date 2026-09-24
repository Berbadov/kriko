import { fireEvent, render, screen, within } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Operations from "./Operations.svelte";
import { stubFetch } from "../lib/stub-fetch";

const ROW = {
    op_id: 7,
    door: "mcp",
    kind: "research",
    name: "submit_findings",
    subject_id: "s1",
    pack_id: "org.kriko.cars",
    state: "ok",
    request_json: '{"subject_id": "s1", "findings": ["… (+900 chars)"]}',
    response_json: '{"accepted": 2, "rejected": 1}',
    error: "",
    ms: 1400,
    started_at: "2026-09-14T10:00:00+00:00",
    ended_at: "2026-09-14T10:00:01+00:00",
};

describe("Operations", () => {
    it("names the door in the reader's words, because 'mcp' is not one", async () => {
        stubFetch({ "/api/operations": { items: [ROW], running: 0, last_id: 7 } });
        render(Operations);
        await screen.findByText("submit_findings");
        // "your agent" rather than "mcp": the reader installed Claude Code,
        // not a protocol. Scoped to the list because the door filter above it
        // names the same doors in the same words — deliberately.
        const list = screen.getByRole("list", { name: "Operations" });
        expect(within(list).getByText(/your agent/)).toBeInTheDocument();
    });

    it("keeps the payload behind a press", async () => {
        stubFetch({ "/api/operations": { items: [ROW], running: 0, last_id: 7 } });
        render(Operations);
        await screen.findByText("submit_findings");
        expect(screen.queryByText(/accepted/)).not.toBeInTheDocument();
        await fireEvent.click(screen.getByRole("button", { name: "Details" }));
        expect(screen.getByText(/"accepted": 2/)).toBeInTheDocument();
    });

    it("says what to do when nothing has happened, rather than showing an empty box", async () => {
        stubFetch({ "/api/operations": { items: [], running: 0, last_id: 0 } });
        render(Operations);
        await screen.findByText("Nothing has happened yet");
        expect(screen.getByText("Connect an agent")).toBeInTheDocument();
    });

    it("shows a failure on the row that failed", async () => {
        stubFetch({
            "/api/operations": {
                items: [{ ...ROW, state: "failed", error: "RuntimeError: no such pack" }],
                running: 0,
                last_id: 7,
            },
        });
        render(Operations);
        await screen.findByText("failed");
        await fireEvent.click(screen.getByRole("button", { name: "Details" }));
        expect(screen.getByText(/no such pack/)).toBeInTheDocument();
    });

    /* A running row.
     *
     * `job_id` is what says the work belongs to the runner in this process,
     * and the joined `note`/`progress` are what the job is saying about
     * itself. Together they are the difference between a spinner and a
     * screen that can be read. */
    const GOING = {
        ...ROW,
        op_id: 8,
        door: "job",
        name: "research",
        state: "running",
        response_json: "",
        ms: null,
        ended_at: "",
        job_id: "j-1",
        note: "extraction",
        progress: 0.5,
        job_state: "running",
    };

    it("says which stage a running operation is in, not merely that it is running", async () => {
        stubFetch({ "/api/operations": { items: [GOING], running: 1, last_id: 8 } });
        render(Operations);
        await screen.findByText("research");
        // The stage in the job's own words, and how far through.
        expect(screen.getByText(/extraction/)).toBeInTheDocument();
        expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "50");
    });

    it("offers Stop only where this installation can actually stop it", async () => {
        // Two running rows: one is a job of this process, one is a call the
        // reader's own agent made and which nothing here can reach into.
        stubFetch({
            "/api/operations": {
                items: [GOING, { ...ROW, op_id: 9, state: "running", ms: null, job_id: "" }],
                running: 2,
                last_id: 9,
            },
        });
        render(Operations);
        await screen.findByText("research");
        expect(screen.getAllByRole("button", { name: "Stop" })).toHaveLength(1);
    });

    it("goes quiet the moment Stop is pressed, because a cancel is cooperative", async () => {
        stubFetch({
            "/api/operations": { items: [GOING], running: 1, last_id: 8 },
            "/api/jobs": { job_id: "j-1", state: "cancelling" },
        });
        render(Operations);
        await screen.findByText("research");
        await fireEvent.click(screen.getByRole("button", { name: "Stop" }));
        // The row keeps running for a moment; the button must not invite a
        // second press that would say nothing new.
        expect(await screen.findByRole("button", { name: "Stopping…" })).toBeDisabled();
    });

    it("filters by door, because 'what did my agent do' is its own question", async () => {
        stubFetch({
            "/api/operations": { items: [GOING, ROW], running: 1, last_id: 8 },
        });
        render(Operations);
        await screen.findByText("research");
        const list = screen.getByRole("list", { name: "Operations" });
        expect(within(list).getByText("submit_findings")).toBeInTheDocument();
        await fireEvent.change(screen.getByLabelText("Door"), { target: { value: "job" } });
        expect(within(list).queryByText("submit_findings")).not.toBeInTheDocument();
        expect(within(list).getByText("research")).toBeInTheDocument();
    });
});
