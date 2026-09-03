import { render, screen } from "@testing-library/svelte";
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

    it("surfaces a failure instead of rendering blank", async () => {
        stubFetchFailing();
        render(Overview);
        expect(await screen.findByText(/Could not load this view/)).toBeInTheDocument();
    });
});
