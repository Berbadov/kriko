import { render, screen, waitFor } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import Usage from "./Usage.svelte";
import { stubFetch, stubFetchFailing } from "./stub-fetch";

/* B97 — the reader said "I see no token info, no usage info etc."
 *
 * Every test here is a variant of one rule: a number nobody measured must
 * not be rendered as zero. `$0.00` on an installation that has never metered
 * anything is the number a reader would quote back at us, and it would be
 * wrong in the direction that flatters us.
 */

const usage = (over: Record<string, unknown> = {}) => ({
    "/api/usage": {
        research: {
            runs: 4,
            metered_runs: 2,
            counted_runs: 3,
            spent_usd: 0.08,
            tokens_used: 1700,
            claims: 4,
            cost_per_claim: 0.02,
            planes: [
                {
                    plane: "harness",
                    runs: 2,
                    metered_runs: 0,
                    spent_usd: null,
                    tokens_used: 900,
                },
                {
                    plane: "api",
                    runs: 2,
                    metered_runs: 2,
                    spent_usd: 0.08,
                    tokens_used: 800,
                },
            ],
            ...(over.research as object),
        },
        analyses: {
            analyses: 12,
            malformed: 0,
            claims_shown: 30,
            answered_nothing: 3,
            subjects: 5,
            adapters: ["a-site"],
            ...(over.analyses as object),
        },
    },
});

describe("what this installation has used", () => {
    it("gives every total the denominator it has to be read against", async () => {
        // A spend of $0.08 means one thing if all four runs were counted and
        // another if two were. A lone figure cannot say which.
        stubFetch(usage());
        render(Usage);
        // Twice on purpose: once as the total, once on the row of the plane
        // that spent all of it.
        await waitFor(() =>
            expect(screen.getAllByText("$0.0800")).toHaveLength(2),
        );
        expect(screen.getByText(/2 of 4 runs counted/)).toBeInTheDocument();
        expect(screen.getByText(/3 runs that could count/)).toBeInTheDocument();
    });

    it("says a number was not counted rather than showing it as zero", async () => {
        stubFetch(
            usage({
                research: {
                    runs: 3,
                    metered_runs: 0,
                    counted_runs: 0,
                    spent_usd: null,
                    tokens_used: null,
                    claims: 5,
                    cost_per_claim: null,
                    planes: [
                        {
                            plane: "agent",
                            runs: 3,
                            metered_runs: 0,
                            spent_usd: null,
                            tokens_used: null,
                        },
                    ],
                },
            }),
        );
        render(Usage);
        await waitFor(() =>
            expect(screen.getAllByText("not counted").length).toBeGreaterThan(1),
        );
        // The one string this panel must never produce out of nulls.
        expect(screen.queryByText("$0.00")).not.toBeInTheDocument();
        expect(screen.queryByText("$0.0000")).not.toBeInTheDocument();
    });

    it("explains an empty spend on a plane that has no marginal cost", async () => {
        // Blank reads as a bug. Two of the three planes genuinely cost
        // nothing beyond a subscription, and that is an answer, not a gap.
        stubFetch(usage());
        render(Usage);
        await waitFor(() =>
            expect(screen.getByText(/no marginal cost/)).toBeInTheDocument(),
        );
        expect(screen.getByText(/started by Kriko/)).toBeInTheDocument();
    });

    it("counts the lookups nobody could answer, not just the lookups", async () => {
        // The analyses log has existed since the first lookup and nothing
        // reachable ever read it. `answered_nothing` is why it is worth
        // reading: those are coverage gaps the reader personally hit.
        stubFetch(usage());
        render(Usage);
        await waitFor(() => expect(screen.getByText("12")).toBeInTheDocument());
        expect(
            screen.getByText(/3 came back with nothing/),
        ).toBeInTheDocument();
    });

    it("points a fresh installation at the planes instead of showing a table", async () => {
        stubFetch(
            usage({
                research: {
                    runs: 0,
                    metered_runs: 0,
                    counted_runs: 0,
                    spent_usd: null,
                    tokens_used: null,
                    claims: 0,
                    cost_per_claim: null,
                    planes: [],
                },
            }),
        );
        render(Usage);
        await waitFor(() =>
            expect(screen.getByText(/nothing to add up/)).toBeInTheDocument(),
        );
        expect(screen.getByRole("link", { name: /Agents/ })).toBeInTheDocument();
    });

    it("says the log lost lines rather than quietly reporting a lower count", async () => {
        stubFetch(usage({ analyses: { malformed: 2 } }));
        render(Usage);
        await waitFor(() =>
            expect(
                screen.getByText(/2 line\(s\) of the analyses log/),
            ).toBeInTheDocument(),
        );
    });

    it("keeps a failed read inline, with a way to try again", async () => {
        stubFetchFailing();
        render(Usage);
        await waitFor(() =>
            expect(screen.getByRole("button", { name: /again/i })).toBeInTheDocument(),
        );
    });

    it("survives a payload with a half missing rather than taking the card down", async () => {
        // An older engine answers `/api/usage` without the `analyses` half.
        // Reading `.planes.length` off an absent `research` threw, which is a
        // worse answer to "what did this cost" than a row of dashes.
        stubFetch({ "/api/usage": {} });
        render(Usage);
        expect(await screen.findByText("What this has used")).toBeInTheDocument();
        expect(screen.getAllByText("not counted").length).toBeGreaterThan(0);
    });
});
