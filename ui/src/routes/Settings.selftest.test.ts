import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Settings from "./Settings.svelte";
import { stubFetch } from "../lib/stub-fetch";

const payload = () => ({
    "/api/settings": {},
    "/api/keys": {
        providers: [
            {
                id: "exa",
                label: "Exa",
                env: "EXA_API_KEY",
                purpose: "Receives search queries built from a subject.",
                present: true,
                hint: "…4f2a",
                source: "file",
            },
            {
                id: "tavily",
                label: "Tavily",
                env: "TAVILY_API_KEY",
                purpose: "Receives the same queries Exa would.",
                present: false,
                hint: "",
                source: "",
            },
            {
                id: "openai",
                label: "OpenAI",
                env: "OPENAI_API_KEY",
                purpose: "Receives the text of pages research fetched.",
                present: true,
                hint: "…9b1c",
                source: "file",
            },
        ],
        ready: true,
        path: "/home/somebody/.kriko/env",
    },
    "/api/prefs": {
        chosen: { preferred_harness: "", llm_model: "", search_provider: "" },
        harnesses: [],
        unusable: [],
        missing: [],
        search_providers: [],
        models: { current: "", default: "", note: "" },
        dirs_env: "",
    },
    "/api/costs": {
        spent: { days: 30, usd: 0, tokens: 0, runs: 0, planes: [] },
        estimates: {},
        balance: { known: false, note: "" },
    },
});

const verdict = (over: Record<string, unknown> = {}) => ({
    provider: "exa",
    ok: true,
    latency_ms: 41,
    error: "",
    detail: "",
    results: 1,
    tokens_in: null,
    tokens_out: null,
    tokens: null,
    usd: null,
    llm: "",
    ...over,
});

describe("the provider self-test", () => {
    it("offers one Test button per provider and disables it without a key", async () => {
        stubFetch(payload());
        render(Settings);
        const buttons = await screen.findAllByRole("button", { name: "Test" });
        expect(buttons).toHaveLength(3);
        const states = buttons.map((one) => (one as HTMLButtonElement).disabled);
        expect(states).toEqual([false, true, false]);
    });

    it("reports ok with latency after a press", async () => {
        stubFetch({ ...payload(), "/api/keys/test": verdict() });
        render(Settings);
        const buttons = await screen.findAllByRole("button", { name: "Test" });
        await fireEvent.click(buttons[0]);
        expect(await screen.findByText(/ok in 41 ms/)).toBeInTheDocument();
        expect(await screen.findByText(/1 result\(s\)/)).toBeInTheDocument();
    });

    it("reports the exact provider error distinctly", async () => {
        stubFetch({
            ...payload(),
            "/api/keys/test": verdict({
                ok: false,
                error: "unauthorized",
                detail: "provider refused the key (HTTP 401)",
                results: null,
            }),
        });
        render(Settings);
        const buttons = await screen.findAllByRole("button", { name: "Test" });
        await fireEvent.click(buttons[0]);
        expect(await screen.findByText(/unauthorized/)).toBeInTheDocument();
        expect(await screen.findByText(/HTTP 401/)).toBeInTheDocument();
    });

    it("disables the button while the check runs", async () => {
        const routes = payload();
        vi.stubGlobal(
            "fetch",
            vi.fn(async (path: string) => {
                const url = String(path);
                if (url.startsWith("/api/keys/test")) {
                    return new Promise(() => {}) as unknown as Response;
                }
                const key = Object.keys(routes)
                    .filter((route) => url.startsWith(route))
                    .sort((a, b) => b.length - a.length)[0];
                if (!key) return new Response(`not stubbed: ${url}`, { status: 500 });
                return new Response(
                    JSON.stringify((routes as Record<string, unknown>)[key]),
                );
            }),
        );
        render(Settings);
        const buttons = await screen.findAllByRole("button", { name: "Test" });
        const target = buttons.find((one) => !(one as HTMLButtonElement).disabled);
        await fireEvent.click(target!);
        await waitFor(() => expect((target as HTMLButtonElement).disabled).toBe(true));
        expect((await screen.findAllByText("Testing...")).length).toBeGreaterThanOrEqual(1);
    });

    it("sends the check to this app only", async () => {
        stubFetch({ ...payload(), "/api/keys/test": verdict() });
        render(Settings);
        const buttons = await screen.findAllByRole("button", { name: "Test" });
        await fireEvent.click(buttons[0]);
        await screen.findByText(/ok in 41 ms/);
        const calls = (fetch as unknown as { mock: { calls: unknown[][] } }).mock.calls;
        expect(calls.length).toBeGreaterThan(0);
        for (const call of calls) {
            expect(String(call[0]).startsWith("/api/")).toBe(true);
        }
        expect(JSON.stringify(calls)).not.toContain("api.exa.ai");
        expect(JSON.stringify(calls)).not.toContain("api.tavily.com");
        expect(JSON.stringify(calls)).not.toContain("api.openai.com");
    });
});
