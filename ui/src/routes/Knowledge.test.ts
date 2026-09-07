import { render, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Knowledge from "./Knowledge.svelte";
import { stubFetch } from "../lib/stub-fetch";

const STATUS = {
    enabled_packs: 1,
    counts: { packs: 1, subjects: 2, claims: 3, evidence: 4 },
};

const PACK = {
    pack_id: "org.kriko.cars",
    name: "Used cars",
    version: "1.0.0",
    enabled: true,
    subjects: 2,
    claims: 3,
};

const MARK = {
    pack_id: "org.kriko.cars",
    claim_id: "c1",
    verdict: "wrong",
    note: "",
    subject_id: "s1",
    title: "Timing chain tensioner wear",
    created_at: "2026-09-06T10:00:00Z",
    updated_at: "2026-09-06T10:00:00Z",
};

function serve(over: Record<string, unknown> = {}) {
    return stubFetch({
        "/api/status": STATUS,
        "/api/packs": [PACK],
        "/api/subjects": [],
        "/api/packs/org.kriko.cars/gaps": [],
        "/api/marks": { items: [], counts: {}, verdicts: ["useful", "not_applicable", "wrong"] },
        "/api/marks/signals": { research: [], matching: [] },
        ...over,
    });
}

describe("Knowledge", () => {
    beforeEach(() => vi.restoreAllMocks());

    it("shows counts before content, so arriving is orientation not a table dump", async () => {
        serve();
        render(Knowledge, {});
        await waitFor(() => expect(screen.getByText("subjects")).toBeInTheDocument());
        expect(screen.getByText("claims")).toBeInTheDocument();
    });

    it("opens on the lens the route named, so an old bookmark still lands right", async () => {
        serve();
        render(Knowledge, { lens: "marked" });
        await waitFor(() =>
            expect(
                screen.getByRole("tab", { name: /What readers said/ }),
            ).toHaveAttribute("aria-selected", "true"),
        );
    });

    it("names every verdict even at zero, so the strip does not change shape", async () => {
        serve();
        render(Knowledge, { lens: "marked" });
        await waitFor(() => expect(screen.getByText("Useful")).toBeInTheDocument());
        // "Not mine" and "Wrong" are separate on purpose: one is a matching
        // problem, the other a knowledge problem.
        expect(screen.getByText("Not mine")).toBeInTheDocument();
        expect(screen.getByText("Wrong")).toBeInTheDocument();
    });

    it("tells an author what a reader called wrong, by the claim's own words", async () => {
        serve({
            "/api/marks": {
                items: [MARK],
                counts: { useful: 0, not_applicable: 0, wrong: 1 },
                verdicts: ["useful", "not_applicable", "wrong"],
            },
        });
        render(Knowledge, { lens: "marked" });
        await waitFor(() =>
            expect(screen.getByText("Timing chain tensioner wear")).toBeInTheDocument(),
        );
        // The title is stored on the mark rather than looked up, so it still
        // reads after the pack that held the claim is uninstalled.
        expect(screen.getByRole("button", { name: "Forget" })).toBeInTheDocument();
    });

    it("explains where verdicts come from when there are none", async () => {
        serve();
        render(Knowledge, { lens: "marked" });
        await waitFor(() =>
            expect(screen.getByText(/No one has marked anything yet/)).toBeInTheDocument(),
        );
        expect(screen.getByText(/browser extension/)).toBeInTheDocument();
    });

    it("turns a pile of wrong verdicts into something an author can start", async () => {
        serve({
            "/api/marks/signals": {
                research: [
                    {
                        subject_id: "s1",
                        pack_id: "org.kriko.cars",
                        count: 2,
                        notes: ["my mechanic says otherwise"],
                        claim_ids: ["c1", "c2"],
                    },
                ],
                matching: [],
            },
        });
        render(Knowledge, { lens: "marked" });
        await waitFor(() =>
            expect(screen.getByText(/Worth researching again/)).toBeInTheDocument(),
        );
        expect(screen.getByText(/2 called wrong/)).toBeInTheDocument();
        // The reader's own words travel with the queue: they are the most
        // useful thing on a mark and the point of collecting one.
        expect(screen.getByText(/my mechanic says otherwise/)).toBeInTheDocument();
        // And a way to act on it, reusing the same brief the gaps lens starts.
        expect(screen.getAllByRole("button", { name: "Research" }).length).toBe(1);
    });

    it("keeps a mismatch out of the research queue and names the door instead", async () => {
        serve({
            "/api/marks/signals": {
                research: [],
                matching: [
                    {
                        subject_id: "s2",
                        pack_id: "org.kriko.cars",
                        count: 1,
                        notes: [],
                        claim_ids: ["c9"],
                        sources: { url: 3 },
                    },
                ],
            },
        });
        render(Knowledge, { lens: "marked" });
        await waitFor(() =>
            expect(screen.getByText(/Matched the wrong thing/)).toBeInTheDocument(),
        );
        // Researching it again would fix nothing, so it is offered no brief.
        expect(screen.queryByRole("button", { name: "Research" })).toBeNull();
        expect(screen.getByText(/suspect what the page was read as/)).toBeInTheDocument();
    });
});
