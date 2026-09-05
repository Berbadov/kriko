import { render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import NextStep from "./NextStep.svelte";
import { stubFetch, stubFetchFailing } from "./stub-fetch";

const ROUTES = {
    "/api/status": { ok: true, packs: 1, enabled_packs: 1, counts: {} },
    "/api/packs": [{ pack_id: "p1", name: "P", version: "1", enabled: 1 }],
    "/api/packs/p1/gaps": [{ subject_id: "s1", label: "One", kind: "k" }],
    "/api/packs/updates": { index_url: "u", error: null, packs: [] },
    "/api/agent-targets": {
        server_name: "kriko",
        store: "/s",
        targets: [{ id: "claude-code", label: "Claude Code", state: "absent" }],
    },
    "/api/history": { items: [{ lookup_id: "l1" }] },
};

describe("the next step bar", () => {
    it("names the thing this installation is actually missing", async () => {
        stubFetch(ROUTES);
        render(NextStep);
        expect(await screen.findByText(/No agent can reach this store/)).toBeTruthy();
        // The link is the point: a hint the reader has to go and find the page
        // for is a sentence, not guidance.
        const action = await screen.findByText("Connect an agent");
        expect(action.getAttribute("href")).toContain("connect");
    });

    it("moves on once that step is done", async () => {
        stubFetch({
            ...ROUTES,
            "/api/agent-targets": {
                server_name: "kriko",
                store: "/s",
                targets: [{ id: "claude-code", label: "C", state: "connected" }],
            },
        });
        render(NextStep);
        expect(await screen.findByText(/1 subject with nothing known/)).toBeTruthy();
    });

    it("says nothing at all when there is nothing to suggest", async () => {
        stubFetch({
            ...ROUTES,
            "/api/packs/p1/gaps": [],
            "/api/agent-targets": {
                server_name: "kriko",
                store: "/s",
                targets: [{ id: "claude-code", label: "C", state: "connected" }],
            },
        });
        const { container } = render(NextStep);
        await vi.waitFor(() => expect(container.querySelector(".nextstep")).toBeNull());
    });

    it("stays silent rather than becoming a second error surface", async () => {
        // An unreachable engine is Health's news to break. A guidance bar that
        // renders a stack trace has stopped being guidance.
        stubFetchFailing();
        const { container } = render(NextStep);
        await vi.waitFor(() => expect(container.querySelector(".nextstep")).toBeNull());
    });

    it("can be dismissed for the session", async () => {
        stubFetch(ROUTES);
        const { container } = render(NextStep);
        (await screen.findByText("Not now")).click();
        await vi.waitFor(() => expect(container.querySelector(".nextstep")).toBeNull());
    });
});
