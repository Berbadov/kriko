import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import { stubFetch, stubFetchFailing } from "../lib/stub-fetch";
import Overview from "./Overview.svelte";

const ROUTES = {
    "/api/status": {
        ok: true,
        packs: 2,
        enabled_packs: 1,
        counts: { subjects: 12, claims: 34 },
    },
    "/api/packs": [
        {
            pack_id: "p1",
            name: "Pack One",
            version: "1.0",
            enabled: 1,
            subjects: 12,
            claims: 34,
            evidence: 9,
            digest: "d",
        },
    ],
    "/api/packs/p1/gaps": [{ subject_id: "s1", label: "One", kind: "k" }],
    "/api/packs/updates": {
        index_url: "u",
        error: null,
        packs: [
            {
                pack_id: "p1",
                name: "Pack One",
                installed_version: "1.0",
                offered_version: "1.1",
                state: "available",
                reason: "",
            },
        ],
    },
    "/api/jobs": {
        items: [
            {
                job_id: "j1",
                kind: "research",
                params: {},
                state: "running",
                progress: 0.4,
                message: "reading",
                log: "",
                result: null,
                done: false,
                created_at: "",
                started_at: null,
                finished_at: null,
            },
        ],
    },
    "/api/adapters/unmapped": {
        labels: [
            {
                adapter_id: "a1",
                label: "Something The Page Said",
                seen: 4,
                first_at: "2026-09-01T00:00:00Z",
                last_at: "2026-09-07T00:00:00Z",
                sample_url: "https://example.test/one",
            },
        ],
    },
    "/api/health/weakest": {
        claims: [
            {
                claim_id: "c1",
                subject_id: "s1",
                subject_label: "One",
                pack_id: "p1",
                title: "Weak thing",
                refuted_by: 0,
                independent_sources: 1,
                best_tier: "forum",
                best_trust: 0.2,
                oldest_retrieved_at: null,
                concern: null,
            },
        ],
    },
};

describe("Overview", () => {
    it("leads with the work waiting, not with the store's size", async () => {
        stubFetch(ROUTES);
        render(Overview);
        expect(await screen.findByText(/1 coverage gap/i)).toBeInTheDocument();
        expect(screen.getByText(/1 pack update/i)).toBeInTheDocument();
        expect(screen.getByText(/1 run in flight/i)).toBeInTheDocument();
    });

    it("still shows the store counts, in a strip rather than as the headline", async () => {
        stubFetch(ROUTES);
        render(Overview);
        expect(await screen.findByText("34")).toBeInTheDocument();
        expect(screen.getByText("Claims")).toBeInTheDocument();
    });

    it("names the weakest claim, so 'what should I work on' has an answer", async () => {
        stubFetch(ROUTES);
        render(Overview);
        expect(await screen.findByText("Weak thing")).toBeInTheDocument();
    });

    it("says the store is empty rather than printing zeroes", async () => {
        stubFetch({
            ...ROUTES,
            "/api/status": { ok: true, packs: 0, enabled_packs: 0, counts: {} },
            "/api/packs": [],
        });
        render(Overview);
        expect(await screen.findByText(/No packs installed/i)).toBeInTheDocument();
    });

    it("names the labels no adapter reads, because nothing else reports them", async () => {
        // A renamed field does not error: the lookup succeeds and returns
        // fewer claims. This table is the only place that difference is
        // visible, so its absence is the bug being fixed.
        stubFetch(ROUTES);
        render(Overview);
        expect(
            await screen.findByText("Something The Page Said"),
        ).toBeInTheDocument();
        expect(screen.getByText("4")).toBeInTheDocument();
        expect(screen.getByText("a1")).toBeInTheDocument();
    });

    it("links a label to the page it was seen on, so it can be checked", async () => {
        stubFetch(ROUTES);
        render(Overview);
        const link = await screen.findByText("Something The Page Said");
        expect(link).toHaveAttribute("href", "https://example.test/one");
    });

    it("strikes a dismissed label through rather than removing the row", async () => {
        // Dismissal is a delete on the server, but the row stays put: one that
        // vanishes under the cursor leaves no way to tell "dismissed" from
        // "misclicked".
        stubFetch(ROUTES);
        render(Overview);
        const button = await screen.findByRole("button", { name: /not a field/i });
        await fireEvent.click(button);
        const row = screen.getByText("Something The Page Said").closest("tr");
        expect(row).toBeInTheDocument();
        // The class is the assertion: `tr.gone td` is what strikes it through,
        // and a test that only checked the text would pass on a row that
        // silently looks untouched.
        expect(row).toHaveClass("gone");
        expect(button).toBeDisabled();
    });

    it("puts a label back when the dismissal did not reach the app", async () => {
        stubFetch({
            ...ROUTES,
            "/api/adapters/unmapped/": { status: 500, body: "boom" },
        });
        render(Overview);
        const button = await screen.findByRole("button", { name: /not a field/i });
        await fireEvent.click(button);
        // Enabled again: a label the app still holds must still be actionable.
        await waitFor(() => expect(button).not.toBeDisabled());
    });

    it("says nothing is unread rather than printing an empty table", async () => {
        stubFetch({ ...ROUTES, "/api/adapters/unmapped": { labels: [] } });
        render(Overview);
        expect(await screen.findByText(/Nothing unread/i)).toBeInTheDocument();
    });

    it("surfaces a failure as something the reader can act on", async () => {
        // B72: the assertion used to be /Could not load this view/, which is
        // the exception's name. What the reader needs is whose fault it is and
        // where the log went.
        stubFetchFailing();
        render(Overview);
        expect(await screen.findByRole("alert")).toBeInTheDocument();
        expect(screen.getByText(/bug in Kriko, not something you did/)).toBeInTheDocument();
    });
});
