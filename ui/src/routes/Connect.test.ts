import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import Connect from "./Connect.svelte";
import { stubFetch, stubFetchFailing } from "../lib/stub-fetch";

const TARGETS = {
    server_name: "kriko",
    store: "/home/reader/.kriko/knowledge.sqlite",
    targets: [
        { id: "claude-code", label: "Claude Code", path: "/home/reader/.claude.json",
          exists: true, state: "connected" },
        { id: "cursor", label: "Cursor", path: "/home/reader/.cursor/mcp.json",
          exists: false, state: "absent" },
        { id: "vscode", label: "VS Code", path: "/home/reader/.vscode/mcp.json",
          exists: true, state: "stale",
          detail: "points at a different store than this window is reading" },
    ],
};

const CONFIG = {
    server_name: "kriko", frozen: true, store: TARGETS.store,
    tools: ["research_brief"],
    mcp_json: { mcpServers: { kriko: { command: "/opt/kriko", args: ["--mcp"] } } },
};

const SKILL = {
    name: "kriko-research",
    steps: [{ tool: "coverage_gaps", why: "find subjects nothing is known about" }],
    body: "---\nname: kriko-research\n---\nKeep only the expensive.",
};

const routes = (over: Record<string, unknown> = {}) =>
    stubFetch({
        "/api/agent-targets": TARGETS,
        "/api/agent-config": CONFIG,
        "/api/agent-skill": SKILL,
        ...over,
    });

afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

describe("connecting an agent", () => {
    it("lists every harness on the machine with what state it is in", async () => {
        routes();
        render(Connect);
        expect(await screen.findByText("Claude Code")).toBeInTheDocument();
        expect(screen.getByText("Connected")).toBeInTheDocument();
        expect(screen.getByText("Not connected")).toBeInTheDocument();
    });

    it("calls a harness pointed at another store 'points elsewhere', not connected", async () => {
        // The failure that looks exactly like success: the agent runs, answers,
        // and files findings into a store this window never reads.
        routes();
        render(Connect);
        expect(await screen.findByText("Points elsewhere")).toBeInTheDocument();
    });

    it("names the file it is about to write, before writing it", async () => {
        routes();
        render(Connect);
        expect(await screen.findByText("/home/reader/.claude.json")).toBeInTheDocument();
    });

    it("connects one harness and re-reads the state rather than assuming it", async () => {
        routes();
        render(Connect);
        await fireEvent.click((await screen.findAllByText("Connect"))[0]);

        const calls = () => (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
        // Re-fetched, not patched locally: the server decides what connected
        // means, and it has just looked at the file.
        await vi.waitFor(() => {
            expect(calls().some(([p]) => p === "/api/agent-targets/cursor/connect")).toBe(true);
            expect(calls().filter(([p]) => p === "/api/agent-targets").length).toBe(2);
        });
    });

    it("keeps one broken harness from hiding the others", async () => {
        routes({ "/api/agent-targets/cursor/connect": { status: 409, body: "not valid JSON" } });
        render(Connect);
        await fireEvent.click((await screen.findAllByText("Connect"))[0]);

        expect(await screen.findByText(/not valid JSON/)).toBeInTheDocument();
        expect(screen.getByText("Claude Code")).toBeInTheDocument();
    });

    it("shows the protocol the agent will be handed", async () => {
        routes();
        render(Connect);
        expect(await screen.findByText("coverage_gaps")).toBeInTheDocument();
        expect(screen.getByText(/Keep only the expensive/)).toBeInTheDocument();
    });

    it("says there is no protocol yet when no pack is installed", async () => {
        routes({ "/api/agent-skill": { ...SKILL, body: null } });
        render(Connect);
        expect(await screen.findByText(/No packs installed/)).toBeInTheDocument();
    });

    it("keeps the paste-it-yourself block for a harness it does not know", async () => {
        routes();
        render(Connect);
        await fireEvent.click(await screen.findByText("Show the config block"));
        expect(screen.getByText(/--mcp/)).toBeInTheDocument();
    });

    it("says what came back when the command is started for real", async () => {
        routes({ "/api/agent-verify": { ok: true, server: "kriko" } });
        render(Connect);
        await fireEvent.click(await screen.findByText("Verify"));
        expect(await screen.findByText("kriko")).toBeInTheDocument();
    });

    it("shows the command's own stderr when it will not start", async () => {
        // The diagnosis is always in stderr — a moved venv, a missing module —
        // and it is the one thing a reader never otherwise sees.
        routes({ "/api/agent-verify":
            { ok: false, detail: "ModuleNotFoundError: No module named 'fastapi'" } });
        render(Connect);
        await fireEvent.click(await screen.findByText("Verify"));
        expect(await screen.findByText(/ModuleNotFoundError/)).toBeInTheDocument();
    });

    it("surfaces a failure instead of rendering an empty page", async () => {
        stubFetchFailing();
        render(Connect);
        expect(await screen.findByText(/Could not read the harness config/)).toBeInTheDocument();
    });
});
