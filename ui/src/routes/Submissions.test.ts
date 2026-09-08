import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Submissions from "./Submissions.svelte";
import { stubFetch } from "../lib/stub-fetch";

const BATCH = {
    submission_id: "b1",
    created_at: "2026-09-06T10:00:00+00:00",
    door: "mcp",
    subject_id: "s1",
    pack_id: "org.kriko.cars",
    accepted: 1,
    refused: 2,
    verdicts: {
        accepted: [{ title: "A kept one", claim_id: "c1" }],
        rejected: [
            { title: "A vague one", reason: "no specific subject — the title names a class" },
            { title: "An unquoted one", reason: "quote not found in the cited document" },
        ],
    },
};

describe("Submissions", () => {
    it("leads with the proportion that got through, not the batch count", async () => {
        stubFetch({
            "/api/submissions": {
                items: [BATCH],
                accepted: 1,
                refused: 2,
                reasons: [{ reason: "quote not found in the cited document", count: 2 }],
            },
        });
        render(Submissions);
        await screen.findByText("33%");
        expect(screen.getByText("got through")).toBeInTheDocument();
    });

    it("groups refusals by rule, because one rule failing often is the thing to fix", async () => {
        stubFetch({
            "/api/submissions": {
                items: [BATCH],
                accepted: 1,
                refused: 2,
                reasons: [{ reason: "quote not found in the cited document", count: 2 }],
            },
        });
        render(Submissions);
        await screen.findByText(/Why findings are refused/);
        expect(
            screen.getByText("quote not found in the cited document"),
        ).toBeInTheDocument();
    });

    it("shows a refused finding's own reason on demand", async () => {
        stubFetch({
            "/api/submissions": { items: [BATCH], accepted: 1, refused: 2, reasons: [] },
        });
        render(Submissions);
        await fireEvent.click(await screen.findByRole("button", { name: "Findings" }));
        expect(screen.getByText("A vague one")).toBeInTheDocument();
        expect(screen.getByText("A kept one")).toBeInTheDocument();
    });

    it("offers no way to accept something the gate refused", async () => {
        stubFetch({
            "/api/submissions": { items: [BATCH], accepted: 1, refused: 2, reasons: [] },
        });
        render(Submissions);
        await fireEvent.click(await screen.findByRole("button", { name: "Findings" }));
        // Not an oversight: nothing in the data path waits on a person, so
        // there is no override to offer. See the automation principle.
        for (const label of [/accept/i, /approve/i, /override/i]) {
            expect(screen.queryByRole("button", { name: label })).toBeNull();
        }
    });

    it("names the door, so a refusal that only happens on one is visible", async () => {
        stubFetch({
            "/api/submissions": { items: [BATCH], accepted: 1, refused: 2, reasons: [] },
        });
        render(Submissions);
        expect(await screen.findByText("mcp")).toBeInTheDocument();
    });

    it("says where findings would come from when none have", async () => {
        stubFetch({
            "/api/submissions": { items: [], accepted: 0, refused: 0, reasons: [] },
        });
        render(Submissions);
        await screen.findByText(/No batches yet/);
        expect(screen.getByRole("link", { name: "Connect an agent" })).toBeInTheDocument();
    });

    it("explains a failure rather than rendering blank", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => new Response("boom", { status: 500 })));
        render(Submissions);
        expect(await screen.findByRole("alert")).toBeInTheDocument();
        expect(screen.getByText(/bug in Kriko, not something you did/)).toBeInTheDocument();
    });
});
