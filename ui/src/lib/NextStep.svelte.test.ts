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

    it("does not re-offer the extension to a reader it has already seen, just because it has been quiet a while", async () => {
        // B85: the live badge on the Extension page (`connected`) goes stale
        // after a few quiet hours on purpose — this bar must not share that
        // clock. A stale-but-ever-seen extension should fall through to
        // whatever the *next* real gap is, not repeat an install that already
        // happened.
        stubFetch({
            ...ROUTES,
            "/api/extension": {
                available: true,
                connected: false,
                ever_connected: true,
            },
        });
        render(NextStep);
        expect(await screen.findByText(/No agent can reach this store/)).toBeTruthy();
        expect(screen.queryByText(/not on your listing pages yet/)).toBeNull();
    });

    it("still offers the extension when it has truly never been seen", async () => {
        stubFetch({
            ...ROUTES,
            "/api/extension": {
                available: true,
                connected: false,
                ever_connected: false,
            },
        });
        render(NextStep);
        expect(
            await screen.findByText(/Kriko is not on your listing pages yet/),
        ).toBeTruthy();
    });

    it("stays dismissed across a reload because the choice was saved, not just held in memory", async () => {
        // A `$state(false)` reset on every mount is indistinguishable, from
        // the reader's side, from "Not now" doing nothing: the same bar they
        // just declined greets them again the moment the app restarts.
        stubFetch({
            ...ROUTES,
            "/api/settings": { nextstep_dismissed_id: "connect-agent" },
        });
        const { container } = render(NextStep);
        await vi.waitFor(() =>
            expect(container.querySelector(".nextstep")).toBeNull(),
        );
        expect(screen.queryByText(/No agent can reach this store/)).toBeNull();
    });

    it("saves the dismissal so it survives the next launch", async () => {
        stubFetch(ROUTES);
        render(NextStep);
        (await screen.findByText("Not now")).click();
        const calls = () =>
            (globalThis.fetch as unknown as { mock: { calls: unknown[][] } }).mock
                .calls;
        await vi.waitFor(() =>
            expect(
                calls().some((call) => String(call[0]) === "/api/settings"),
            ).toBe(true),
        );
        const [, init] = calls().find(
            (call) =>
                String(call[0]) === "/api/settings" &&
                (call[1] as RequestInit | undefined)?.method === "POST",
        ) as [string, RequestInit];
        expect(JSON.parse(String(init.body)).values).toEqual({
            nextstep_dismissed_id: "connect-agent",
        });
    });
});
