import { render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Dashboard from "./Dashboard.svelte";

const STATUS = {
    ok: true,
    packs: 2,
    enabled_packs: 1,
    counts: { subjects: 12, claims: 34 },
};

function stubFetch(routes: Record<string, unknown>) {
    vi.stubGlobal(
        "fetch",
        vi.fn(async (path: string) => {
            const key = Object.keys(routes).find((r) => path.startsWith(r));
            if (!key) return new Response("not stubbed", { status: 500 });
            return new Response(JSON.stringify(routes[key]));
        }),
    );
}

describe("Dashboard", () => {
    it("shows the store counts", async () => {
        stubFetch({ "/api/status": STATUS, "/api/activity": { items: [], malformed: 0 } });
        render(Dashboard);
        expect(await screen.findByText("34")).toBeInTheDocument();
        expect(await screen.findByText("Claims")).toBeInTheDocument();
    });

    it("says so when there is no activity, rather than showing an empty table", async () => {
        stubFetch({ "/api/status": STATUS, "/api/activity": { items: [], malformed: 0 } });
        render(Dashboard);
        expect(await screen.findByText(/No analysis activity yet/)).toBeInTheDocument();
    });

    it("surfaces a failure instead of rendering blank", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => new Response("boom", { status: 500 })));
        render(Dashboard);
        expect(await screen.findByText(/Could not load this view/)).toBeInTheDocument();
    });
});
