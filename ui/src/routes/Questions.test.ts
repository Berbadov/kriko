import { fireEvent, render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { stubFetch } from "../lib/stub-fetch";
import Questions from "./Questions.svelte";

const claim = (id: string, severity: string, advice: string) => ({
    claim_id: id,
    title: `T-${id}`,
    body: "b",
    advice,
    severity,
    domain: "mech",
    subject: "s",
    relevance: 0.5,
    pack_id: "p",
});

const SHEET = {
    "/api/history": {
        items: [
            {
                lookup_id: "L1",
                created_at: "2026-09-01",
                source: "url",
                label: "The one",
                claim_count: 2,
            },
        ],
    },
    "/api/lookup/L1": {
        lookup_id: "L1",
        created_at: "",
        source: "url",
        label: "The one",
        request: {},
        response: {
            method: "exact",
            coverage: "RISKS_FOUND",
            claims: [
                claim("l", "low", "Ask about the tyres."),
                claim("h", "high", "Ask for the receipt."),
            ],
        },
    },
    "/api/lookups/L1/triage": { checked: [], notes: {} },
};

describe("Questions — the sheet you take to the seller", () => {
    beforeEach(() => {
        window.location.hash = "#/questions";
    });

    it("resolves the newest saved answer when the link names none", async () => {
        // Inspection day: they open this from the rail, not from a report.
        stubFetch(SHEET);
        render(Questions, { lookupId: "" });
        expect(
            await screen.findByRole("heading", { name: /Questions for The one/ }),
        ).toBeInTheDocument();
    });

    it("lists the asks worst first, not the claim titles", async () => {
        stubFetch(SHEET);
        render(Questions, { lookupId: "L1" });
        const asks = await screen.findAllByText(/^Ask /);
        expect(asks.map((el) => el.textContent)).toEqual([
            "Ask for the receipt.",
            "Ask about the tyres.",
        ]);
    });

    it("writes an answer against the same stored lookup the report does", async () => {
        const fetcher = vi.fn(async (path: string, init?: RequestInit) => {
            if (init?.method === "POST") {
                return new Response(JSON.stringify({ notes: { h: "said no receipt" } }));
            }
            const key = Object.keys(SHEET)
                .filter((route) => path.startsWith(route))
                .sort((a, b) => b.length - a.length)[0];
            return new Response(JSON.stringify(SHEET[key as keyof typeof SHEET]));
        });
        vi.stubGlobal("fetch", fetcher);
        render(Questions, { lookupId: "L1" });
        const boxes = await screen.findAllByPlaceholderText("What did they say?");
        await fireEvent.blur(boxes[0], { target: { value: "said no receipt" } });
        const [path, init] = fetcher.mock.calls.at(-1)!;
        expect(path).toBe("/api/lookups/L1/notes");
        expect(JSON.parse(String(init!.body))).toEqual({
            claim_key: "h",
            note: "said no receipt",
        });
    });

    it("collapses to one question at a time for a phone in a car park", async () => {
        stubFetch(SHEET);
        render(Questions, { lookupId: "L1" });
        await fireEvent.click(await screen.findByRole("button", { name: "One at a time" }));
        expect(await screen.findByText(/1\s+of\s+2/)).toBeInTheDocument();
        // The other question is off screen entirely — that is the whole point.
        expect(screen.queryByText("Ask about the tyres.")).not.toBeInTheDocument();
    });

    it("explains itself rather than blanking when there is no saved check", async () => {
        stubFetch({ "/api/history": { items: [] } });
        render(Questions, { lookupId: "" });
        expect(await screen.findByText(/No saved check/)).toBeInTheDocument();
    });

    it("says a coverage gap is not a clean bill when a saved answer is empty", async () => {
        stubFetch({
            ...SHEET,
            "/api/lookup/L1": {
                ...SHEET["/api/lookup/L1"],
                response: { method: "exact", coverage: "NO_RISKS", claims: [] },
            },
        });
        render(Questions, { lookupId: "L1" });
        expect(await screen.findByText(/coverage gap, not a/)).toBeInTheDocument();
    });
});
