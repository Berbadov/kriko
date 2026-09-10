import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import Planes from "./Planes.svelte";
import { stubFetch, stubFetchFailing } from "./stub-fetch";

const planes = (apiReady: boolean) => ({
    "/api/research-planes": {
        planes: [
            {
                id: "harness",
                cost_basis: "subscription",
                what: "Kriko starts the coding agent you already pay for.",
                ready: true,
                needs_keys: false,
                harnesses: [
                    { id: "claude-code", label: "Claude Code", command: "claude" },
                ],
                looked_for: ["claude", "opencode"],
                unusable: [
                    {
                        id: "opencode",
                        label: "opencode",
                        command: "opencode",
                        why: "no flag restricts which tools the agent may use",
                    },
                ],
            },
            {
                id: "agent",
                cost_basis: "subscription",
                what: "Your coding agent does the reading, through the MCP server.",
                ready: true,
                needs_keys: false,
            },
            {
                id: "api",
                cost_basis: "per_token",
                what: "Kriko searches and reads by itself, unattended.",
                ready: apiReady,
                needs_keys: true,
            },
        ],
        // What an unnamed run resolves to here. The reader met the cost of not
        // knowing this: the default was the plane that fetches nothing.
        default: "harness",
    },
    "/api/agenda/run": { job_id: "j1", kind: "agenda_run" },
    "/api/jobs/j1": {
        job_id: "j1",
        kind: "agenda_run",
        state: "running",
        done: false,
        message: "working down the agenda",
        log: "",
        result: null,
        progress: 0.2,
    },
});

describe("the three research planes", () => {
    it("shows all three, so the reader can see what their options are", async () => {
        stubFetch(planes(true));
        render(Planes);
        expect(await screen.findByText("Run my agent")).toBeTruthy();
        expect(await screen.findByText("I'll run it myself")).toBeTruthy();
        expect(await screen.findByText("Kriko itself")).toBeTruthy();
        // Each plane's cost, in words a reader can act on rather than the
        // engine's own `cost_basis` alone. Two planes cost nothing marginal —
        // one drives an agent, one waits for you to — so that phrase is now
        // on the page twice, and finding it once would be the wrong assertion.
        expect((await screen.findAllByText("no marginal cost")).length).toBe(2);
        expect(await screen.findByText("costs per token")).toBeTruthy();
    });

    it("keeps the engine's own cost word on the page", async () => {
        stubFetch(planes(true));
        const { container } = render(Planes);
        await screen.findByText("I'll run it myself");
        // Someone grepping the codebase for `per_token` should find it here
        // too — the translated phrase is for the reader, not a replacement.
        const titles = [...container.querySelectorAll("[title]")].map((n) =>
            n.getAttribute("title"),
        );
        expect(titles).toContain("subscription");
        expect(titles).toContain("per_token");
    });

    it("makes the paid plane inert and names its prerequisite", async () => {
        stubFetch(planes(false));
        const { container } = render(Planes);
        expect(await screen.findByText(/Needs both keys/)).toBeTruthy();
        // A link to where the keys are set, because "needs keys" without a
        // destination is the dead end this whole screen exists to remove.
        const link = container.querySelector('a[href="#/settings"]');
        expect(link).toBeTruthy();
        // Dimmed, not hidden: half the answer to "what are my options" is the
        // option that is not available yet.
        expect(container.querySelector(".plane.inert")).toBeTruthy();
        expect(screen.getByText("Kriko itself")).toBeTruthy();
    });

    it("offers a budget only on the plane that spends", async () => {
        stubFetch(planes(true));
        const { container } = render(Planes);
        await screen.findByText("I'll run it myself");
        const sections = [...container.querySelectorAll(".plane")];
        const free = sections.find((s) => s.textContent?.includes("I'll run it myself"))!;
        const paid = sections.find((s) => s.textContent?.includes("Kriko itself"))!;
        expect(free.textContent).not.toContain("Ceiling");
        expect(paid.textContent).toContain("Ceiling");
        // And the hard-stop wording, because a ceiling read as a warning is
        // the one misunderstanding that produces a bill.
        expect(paid.textContent).toContain("hard stop");
    });

    it("starts one job for the whole run and follows it", async () => {
        stubFetch(planes(true));
        const { container } = render(Planes);
        await screen.findByText("I'll run it myself");

        const free = [...container.querySelectorAll(".plane")].find((s) =>
            s.textContent?.includes("I'll run it myself"),
        )!;
        (free.querySelector("form") as HTMLFormElement).dispatchEvent(
            new Event("submit", { bubbles: true, cancelable: true }),
        );
        await new Promise((resolve) => setTimeout(resolve, 0));

        const calls = (fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls;
        const runs = calls.filter((call) => String(call[0]) === "/api/agenda/run");
        // One request for however many subjects: `agenda_run` loops inline,
        // because the job runner has a single worker and a job that submits
        // jobs would wait behind itself forever.
        expect(runs.length).toBe(1);
        const sent = JSON.parse(String((runs[0][1] as RequestInit).body));
        expect(sent.backend).toBe("agent");
        // Zero on the free plane: it is the honest number, and the server is
        // what refuses to read zero as unlimited on the paid one.
        expect(sent.budget_usd).toBe(0);
    });

    it("offers the plane that drives the agent itself, and says which one", async () => {
        // B92. The plane the reader's complaint was actually about: before it
        // existed, both of the others ended in somebody else doing the reading.
        stubFetch(planes(true));
        const { container } = render(Planes);
        expect(await screen.findByText("Run my agent")).toBeTruthy();
        const harness = [...container.querySelectorAll(".plane")].find((s) =>
            s.textContent?.includes("Run my agent"),
        )!;
        // Which CLI it found, because "run my agent" without naming it is a
        // button the reader cannot predict.
        expect(harness.textContent).toContain("Claude Code");

        (harness.querySelector("form") as HTMLFormElement).dispatchEvent(
            new Event("submit", { bubbles: true, cancelable: true }),
        );
        await new Promise((resolve) => setTimeout(resolve, 0));
        const calls = (fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls;
        const runs = calls.filter((call) => String(call[0]) === "/api/agenda/run");
        expect(JSON.parse(String((runs[0][1] as RequestInit).body)).backend).toBe(
            "harness",
        );
    });

    it("surfaces a failure instead of rendering an empty card", async () => {
        stubFetchFailing();
        render(Planes);
        expect(await screen.findByText("Build knowledge")).toBeTruthy();
        expect(await screen.findByRole("button", { name: /again|retry/i })).toBeTruthy();
    });

    it("marks the plane an unnamed run will actually use", async () => {
        stubFetch(planes(true));
        render(Planes);
        // Not decoration. Research reported success having gathered nothing
        // because the default was the plane that fetches nothing by design,
        // and no screen said which plane that was.
        expect(await screen.findByText("default")).toBeInTheDocument();
    });

    it("says why an installed agent is not being used", async () => {
        stubFetch(planes(true));
        render(Planes);
        // "My opencode is installed, why isn't Kriko using it" is a fair
        // question, and silence reads as Kriko failing to notice a tool the
        // reader can see on their own PATH.
        expect(
            await screen.findByText(/no flag restricts which tools/),
        ).toBeInTheDocument();
    });
});
