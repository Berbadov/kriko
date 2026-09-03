import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Report from "./Report.svelte";
import { stubFetch } from "./stub-fetch";
import type { LookupResult } from "./types";

const RESULT: LookupResult = {
    method: "exact",
    coverage: "RISKS_FOUND",
    claims: [
        {
            claim_id: "c1",
            title: "Spindle runout",
            body: "Wears with duty cycles.",
            advice: "Ask for the service record.",
            severity: "high",
            domain: "mech",
            subject: "Bench Grinder 8in",
            pack_id: "tools",
            relevance: 0.2712,
            why: ["high severity", "best source is specialist (trust 0.80)"],
            sources: [
                { domain: "forum.test", quote: "mine went at 300h", tier: "forum_ugc", stance: "supports" },
            ],
        },
    ],
};

const ok = (body: unknown) => new Response(JSON.stringify(body));

describe("Report — one payload, two renderings", () => {
    it("gives a buyer urgency and what to ask, not the score", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => ok({ checked: [] })));
        render(Report, { props: { result: RESULT, mode: "buyer" } });
        expect(await screen.findByText("Serious")).toBeInTheDocument();
        expect(await screen.findByText(/Ask for the service record/)).toBeInTheDocument();
        // The count appears twice by design: on the claim's meta line and on
        // the collapsed sources summary.
        expect(await screen.findAllByText(/1 source reports this/)).not.toHaveLength(0);
        expect(screen.queryByText(/relevance/)).not.toBeInTheDocument();
        expect(screen.queryByText(/forum_ugc/)).not.toBeInTheDocument();
    });

    it("gives an author the score, the pack and the reasons", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => ok({ checked: [] })));
        render(Report, { props: { result: RESULT, mode: "author" } });
        expect(await screen.findByText(/relevance 0.2712/)).toBeInTheDocument();
        expect(await screen.findByText(/best source is specialist/)).toBeInTheDocument();
    });

    it("groups under the pack's own domain and counts the serious ones", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => ok({ checked: [] })));
        render(Report, { props: { result: RESULT } });
        expect(await screen.findByRole("heading", { name: "mech" })).toBeInTheDocument();
        expect(await screen.findByText(/1 serious/)).toBeInTheDocument();
    });

    it("persists a handled risk against the stored lookup", async () => {
        const fetcher = vi.fn(async (path: string, init?: RequestInit) =>
            init?.method === "POST" ? ok({ checked: ["c1"] }) : ok({ checked: [] }),
        );
        vi.stubGlobal("fetch", fetcher);
        render(Report, { props: { result: RESULT, lookupId: "abc" } });
        await fireEvent.click(await screen.findByLabelText("Handled"));
        expect(await screen.findByText(/1 handled/)).toBeInTheDocument();
        const [path, init] = fetcher.mock.calls.at(-1)!;
        expect(path).toBe("/api/lookups/abc/checked");
        expect(JSON.parse(String(init!.body))).toEqual({
            claim_key: "c1",
            checked: true,
        });
    });

    it("says why an empty report is empty, and which kind of empty it is", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => ok({ checked: [] })));
        const { unmount } = render(Report, {
            props: { result: { method: "no_match", coverage: "NOT_MATCHED", claims: [] } },
        });
        expect(await screen.findByText(/No installed pack recognised/)).toBeInTheDocument();
        unmount();
        render(Report, {
            props: { result: { method: "exact", coverage: "NO_RISKS", claims: [] } },
        });
        expect(await screen.findByText(/coverage gap, not a clean bill/)).toBeInTheDocument();
    });

    it("leads with a verdict, not with a bare count", async () => {
        stubFetch({ "/api/lookups/L1/checked": { checked: [] } });
        render(Report, { result: RESULT, lookupId: "L1" });
        expect(await screen.findByText(/serious/)).toBeInTheDocument();
        expect(screen.getByRole("img", { name: /severity mix/i })).toBeInTheDocument();
    });

    it("shows the reader how the match was made beside the verdict", () => {
        stubFetch({ "/api/lookups/L1/checked": { checked: [] } });
        render(Report, { result: RESULT, lookupId: "L1" });
        expect(screen.getByText(/Matched/)).toBeInTheDocument();
    });
});
