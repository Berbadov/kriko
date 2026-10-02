import { render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Home from "./Home.svelte";
const today = new Date().toISOString();
function stub() {
    vi.stubGlobal(
        "fetch",
        vi.fn(async (url: string) => {
            const body = url.includes("/api/operations")
                ? { items: [{ op_id: 1, kind: "lookup", started_at: today }], running: 0, last_id: 1 }
                : url.includes("/api/jobs")
                  ? { items: [{ job_id: "a", finished_at: today, result: { accepted: 3, spent_usd: 0.4 } }] }
                  : url.includes("/api/history")
                    ? { items: [] }
                    : { research: { claims: 3, spent_usd: 0.4, runs: 1, metered_runs: 1 }, analyses: { analyses: 1 } };
            return new Response(JSON.stringify(body));
        }),
    );
}
describe("Home", () => {
    it("shows three graphs under named sections, with no paragraph under any title", async () => {
        stub();
        const { container } = render(Home, {});
        // The design system's page frame: crumb, display title, one-line lead.
        expect(await screen.findByRole("heading", { name: "Home" })).toBeInTheDocument();
        expect(await screen.findAllByRole("img", { name: /over the last 14 days/ })).toHaveLength(3);
        // Four cards at rest: three graphs and the recent checks table.
        expect(container.querySelectorAll(".k-card").length).toBeGreaterThanOrEqual(4);
        expect(container.querySelectorAll("section > p").length).toBe(0);
    });
});
