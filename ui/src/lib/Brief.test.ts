import { render, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Brief from "./Brief.svelte";
import { stubFetch } from "./stub-fetch";

const DONE = {
    job_id: "j1",
    kind: "research",
    params: {},
    state: "succeeded",
    progress: 1,
    message: "done",
    done: true,
    log: [],
    result: {
        plane: "agent",
        documents: 0,
        brief: "Look for reports of the tensioner failing before 150k.",
        queries: ["tensioner failure", "tensioner recall"],
        accepted: [],
        rejected: [],
    },
};

function serve(job: unknown) {
    stubFetch({
        "/api/research": { job_id: "j1" },
        // Longer prefix, so it must be stubbed separately: "/api/research"
        // would otherwise answer the planes call with a job id, and the card
        // asks for the planes to decide whether it can offer to run one.
        "/api/research-planes": {
            planes: [
                {
                    id: "harness",
                    cost_basis: "subscription",
                    what: "Kriko starts the coding agent you already pay for.",
                    ready: true,
                    needs_keys: false,
                },
            ],
        },
        "/api/jobs/j1": job,
    });
}

const PROPS = { subjectId: "s1", packId: "p1", label: "the subject" };

describe("Brief", () => {
    beforeEach(() => vi.restoreAllMocks());

    it("shows the artifact, not just the job's state word", async () => {
        // The bug this component exists for: the $0 plane's job succeeded,
        // wrote a full brief, and the screen rendered the word "done". A
        // button whose entire visible output is a state word is a dead button.
        serve(DONE);
        render(Brief, PROPS);
        await waitFor(() =>
            expect(
                screen.getByText(/Look for reports of the tensioner/),
            ).toBeInTheDocument(),
        );
    });

    it("says nothing was searched, before showing what to search for", async () => {
        // Answering the reader's actual question at that moment. `gather()`
        // returning nothing is the design, not a failure, and burying that
        // under a scroll is how the feature came to look broken.
        serve(DONE);
        render(Brief, PROPS);
        await waitFor(() =>
            expect(screen.getByText(/Kriko searched nothing/)).toBeInTheDocument(),
        );
        // And what to do about it. B92 gave the sentence a second half — the
        // reader can have Kriko start the agent, or hand the brief over — so
        // the assertion tracks the instruction rather than the old wording.
        expect(
            screen.getByText(/hand it the brief yourself/),
        ).toBeInTheDocument();
    });

    it("offers the brief as something to hand off, with the queries counted", async () => {
        serve(DONE);
        render(Brief, PROPS);
        await waitFor(() =>
            expect(
                screen.getByRole("button", { name: "Copy the brief" }),
            ).toBeInTheDocument(),
        );
        expect(
            screen.getByRole("button", { name: "Copy 2 queries" }),
        ).toBeInTheDocument();
        // The other way to spend the brief: an agent already connected can
        // submit findings back through the checked acceptance path.
        expect(
            screen.getByRole("link", { name: "Connect an agent" }),
        ).toBeInTheDocument();
    });

    it("names a finished run that produced no brief, rather than showing blank", async () => {
        serve({ ...DONE, result: {} });
        render(Brief, PROPS);
        await waitFor(() =>
            expect(screen.getByText(/produced no brief/)).toBeInTheDocument(),
        );
    });

    it("keeps a research failure inline, so the screen behind it survives", async () => {
        stubFetch({ "/api/research": { status: 409, body: '{"detail":"a job is running"}' } });
        render(Brief, PROPS);
        await waitFor(() =>
            expect(
                screen.getByText(/already doing this/i),
            ).toBeInTheDocument(),
        );
    });
});
