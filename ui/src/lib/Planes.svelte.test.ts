import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import Planes from "./Planes.svelte";
import { stubFetch, stubFetchFailing } from "./stub-fetch";

const planes = (apiReady: boolean) => ({
    "/api/research-planes": {
        planes: [
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

describe("the two research planes", () => {
    it("shows both, so the reader can see what their options are", async () => {
        stubFetch(planes(true));
        render(Planes);
        expect(await screen.findByText("Your agent")).toBeTruthy();
        expect(await screen.findByText("Kriko itself")).toBeTruthy();
        // Each plane's cost, in words a reader can act on rather than the
        // engine's own `cost_basis` alone.
        expect(await screen.findByText("no marginal cost")).toBeTruthy();
        expect(await screen.findByText("costs per token")).toBeTruthy();
    });

    it("keeps the engine's own cost word on the page", async () => {
        stubFetch(planes(true));
        const { container } = render(Planes);
        await screen.findByText("Your agent");
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
        await screen.findByText("Your agent");
        const sections = [...container.querySelectorAll(".plane")];
        const free = sections.find((s) => s.textContent?.includes("Your agent"))!;
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
        await screen.findByText("Your agent");

        const free = [...container.querySelectorAll(".plane")].find((s) =>
            s.textContent?.includes("Your agent"),
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

    it("surfaces a failure instead of rendering an empty card", async () => {
        stubFetchFailing();
        render(Planes);
        expect(await screen.findByText("Build knowledge")).toBeTruthy();
        expect(await screen.findByRole("button", { name: /again|retry/i })).toBeTruthy();
    });
});
