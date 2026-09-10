import { render, screen, waitFor } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import Schedule from "./Schedule.svelte";
import { stubFetch, stubFetchFailing } from "./stub-fetch";

const off = {
    enabled: false,
    every_hours: 24,
    rows: 5,
    plane: "harness",
    budget_usd: 0,
    max_documents: 5,
    last: {},
    in_flight: 0,
};

/* Both routes, explicitly. `/api/schedule` is a prefix of
 * `/api/schedule/check`, and the stub matches by longest prefix — so a test
 * that stubbed only the first would answer "check now" with the settings
 * payload and quietly assert nothing. */
const routes = (over: Record<string, unknown> = {}, check: Record<string, unknown> = {}) => ({
    "/api/schedule": { ...off, ...over },
    "/api/schedule/check": { ...off, ...over, ran: false, reason: "…", due_at: "", ...check },
});

describe("the unattended loop, as the reader sees it", () => {
    it("says it is off on an installation that never turned it on", async () => {
        stubFetch(routes());
        render(Schedule);
        expect(await screen.findByText("Off")).toBeInTheDocument();
    });

    it("leads with what the last check decided, because on a quiet day that is the only output", async () => {
        stubFetch(
            routes({
                enabled: true,
                last: {
                    checked_at: "2026-09-10T12:00:00+00:00",
                    reason: "no coding-agent command-line tool was found on PATH",
                },
            }),
        );
        render(Schedule);
        expect(
            await screen.findByText(/no coding-agent command-line tool/),
        ).toBeInTheDocument();
    });

    it("says it has not checked yet rather than showing an empty row", async () => {
        stubFetch(routes());
        render(Schedule);
        expect(await screen.findByText("It has not checked yet.")).toBeInTheDocument();
    });

    it("names the interval in words, so 'on' is never on its own", async () => {
        stubFetch(routes({ enabled: true, every_hours: 24 }));
        render(Schedule);
        expect(await screen.findByText("On — daily")).toBeInTheDocument();
    });

    it("does not offer the plane whose output needs a person to hand it over", async () => {
        stubFetch(routes());
        render(Schedule);
        await screen.findByText("Off");
        // The `agent` plane writes a brief for somebody to carry to an agent.
        // Unattended, that brief is never read — so it is not on the menu.
        expect(screen.queryByRole("option", { name: "I'll run it myself" })).toBeNull();
        expect(screen.getByRole("option", { name: "Run my agent" })).toBeInTheDocument();
    });

    it("asks for a ceiling only on the plane that spends money", async () => {
        stubFetch(routes({ plane: "api", budget_usd: 0.5 }));
        render(Schedule);
        expect(await screen.findByText("Ceiling per run, $")).toBeInTheDocument();
    });

    it("keeps the ceiling off screen on the plane with no marginal cost", async () => {
        stubFetch(routes({ plane: "harness" }));
        render(Schedule);
        await screen.findByText("Off");
        expect(screen.queryByText("Ceiling per run, $")).toBeNull();
    });

    it("says work is in flight rather than looking idle while it waits", async () => {
        stubFetch(routes({ enabled: true, in_flight: 2 }));
        render(Schedule);
        expect(await screen.findByText(/2 jobs queued or running/)).toBeInTheDocument();
    });

    it("survives a payload from an engine that has no schedule to report", async () => {
        // Found by the route tests rather than by design: `Agents.test.ts`
        // stubs a partial payload, and reading `.last.reason` off an absent
        // field took the card down — costing the reader the off switch as
        // well as the history. The card fills in what did not arrive.
        stubFetch({ "/api/schedule": {} });
        render(Schedule);
        expect(await screen.findByText("Off")).toBeInTheDocument();
        expect(screen.getByText("It has not checked yet.")).toBeInTheDocument();
    });

    it("surfaces a failure instead of rendering blank", async () => {
        stubFetchFailing();
        render(Schedule);
        // The heading stays — a card that vanishes on a failed read tells the
        // reader the feature does not exist rather than that a read failed.
        expect(await screen.findByText("On a schedule")).toBeInTheDocument();
        await waitFor(() =>
            expect(screen.getByRole("button", { name: /again|retry/i })).toBeInTheDocument(),
        );
    });
});
