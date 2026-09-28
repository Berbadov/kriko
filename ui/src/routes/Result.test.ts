import { render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import Result from "./Result.svelte";

const STORED = {
    lookup_id: "abc123",
    created_at: "2026-09-01T10:00:00+00:00",
    source: "ask",
    label: "Bench Grinder 8in",
    request: { kind: "product", identity: { brand: "acme" } },
    response: {
        method: "exact",
        coverage: "RISKS_FOUND",
        claims: [
            {
                title: "Spindle runout",
                body: "Wears with duty cycles.",
                severity: "high",
                subject: "Bench Grinder 8in",
                pack_id: "tools",
                relevance: 0.27,
            },
        ],
    },
};

afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
});

describe("Result", () => {
    it("renders a stored lookup from its id", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(STORED))));
        render(Result, { props: { lookupId: "abc123" } });
        expect(await screen.findByText("Spindle runout")).toBeInTheDocument();
        // The label is both the heading and the claim's subject line, so ask
        // for the heading specifically rather than the first match.
        expect(
            await screen.findByRole("heading", { name: "Bench Grinder 8in" }),
        ).toBeInTheDocument();
    });

    it("says the lookup is gone rather than rendering blank", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async () => new Response("no such lookup", { status: 404 })),
        );
        render(Result, { props: { lookupId: "gone" } });
        expect(await screen.findByText(/no longer in your history/)).toBeInTheDocument();
    });

    it("a card an agent adds while the answer is open appears, marked New", async () => {
        vi.useFakeTimers({ shouldAdvanceTime: true });
        let clock = "b-0";
        const added = {
            ...STORED,
            response: {
                ...STORED.response,
                claims: [
                    ...STORED.response.claims,
                    { ...STORED.response.claims[0], title: "Guard cracks", severity: "medium" },
                ],
            },
        };
        const refreshed: string[] = [];
        vi.stubGlobal("fetch", vi.fn(async (url: string) => {
            if (url.startsWith("/api/knowledge/clock"))
                return new Response(JSON.stringify({ clock }));
            if (url.endsWith("/refresh")) {
                refreshed.push(url);
                return new Response(JSON.stringify({ ...added, refreshed: true, clock }));
            }
            return new Response(JSON.stringify(STORED));
        }));
        render(Result, { props: { lookupId: "abc123" } });
        expect(await screen.findByText("Spindle runout")).toBeInTheDocument();
        // Nothing moved: no re-answer.
        await vi.advanceTimersByTimeAsync(3000);
        expect(refreshed).toEqual([]);
        expect(screen.queryByText("Guard cracks")).toBeNull();

        clock = "b-1";
        await vi.advanceTimersByTimeAsync(2000);
        expect(await screen.findByText("Guard cracks")).toBeInTheDocument();
        expect(refreshed).toEqual(["/api/lookup/abc123/refresh"]);
        // Only the arrival is New; the card that was already there is not.
        expect(screen.getAllByText("New")).toHaveLength(1);
    });
});
