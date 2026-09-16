import { fireEvent, render, screen } from "@testing-library/svelte";
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
        // not a protocol.
        expect(screen.getByText(/your agent/)).toBeInTheDocument();
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
});
