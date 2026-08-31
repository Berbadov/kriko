import { render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
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
});
