import { cleanup, fireEvent, render, screen, within } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import Connect from "./Connect.svelte";
import { stubFetch, stubFetchFailing } from "../lib/stub-fetch";

const TARGETS = {
    server_name: "kriko",
    store: "/home/reader/.kriko/knowledge.sqlite",
    targets: [
        { id: "claude-code", label: "Claude Code", path: "/home/reader/.claude.json",
          exists: true, state: "connected",
          skill: { supported: true, path: "/home/reader/.claude/skills", present: true, stale: false } },
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

// One CLI that is also an MCP client (same id) and one that is not.
const PREFS = {
    chosen: { preferred_harness: "" },
    harnesses: [
        { id: "claude-code", label: "Claude Code", path: "/bin/claude", llms: [], efforts: [],
          llm_selectable: false },
        { id: "opencode", label: "OpenCode", path: "/bin/opencode", llms: [], efforts: [],
          llm_selectable: false },
    ],
    unusable: [],
    missing: [],
};

const routes = (over: Record<string, unknown> = {}) =>
    stubFetch({
        "/api/agent-targets": TARGETS,
        "/api/agent-config": CONFIG,
        "/api/prefs": PREFS,
        ...over,
    });

const calls = () => (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;

afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
});

describe("the Agents screen", () => {
    it("shows the agents and none of the sections that were removed", async () => {
        routes();
        render(Connect);
        expect(await screen.findByText("Your agents")).toBeInTheDocument();
        expect(screen.getByText("Does it actually run?")).toBeInTheDocument();
        for (const gone of [
            "Harnesses on this machine",
            "What to research next",
            "Build knowledge",
            "On a schedule",
            "What the agent is told",
        ]) {
            expect(screen.queryByText(gone)).toBeNull();
        }
        // Nothing on this screen asks for the top-N run or the schedule either.
        expect(calls().some(([p]) => String(p).includes("/api/schedule"))).toBe(false);
        expect(calls().some(([p]) => String(p).includes("/api/agenda"))).toBe(false);
        expect(calls().some(([p]) => String(p).includes("/api/research-planes"))).toBe(false);
    });

    it("puts each agent's connection state on its own row", async () => {
        routes();
        render(Connect);
        expect((await screen.findAllByText("OpenCode")).length).toBeGreaterThan(0);
        expect(await screen.findByText("Connected")).toBeInTheDocument();
        // An MCP client that has no CLI of its own still gets a row, so its
        // Connect action did not disappear with the old section.
        expect(screen.getByText("Cursor")).toBeInTheDocument();
        expect(screen.getByText("Not connected")).toBeInTheDocument();
    });

    it("calls a client pointed at another store 'points elsewhere', not connected", async () => {
        // The failure that looks exactly like success: the agent runs, answers,
        // and files findings into a store this window never reads.
        routes();
        render(Connect);
        expect(await screen.findByText("Points elsewhere")).toBeInTheDocument();
    });

    it("names the file it is about to write, before writing it", async () => {
        routes();
        render(Connect);
        expect(await screen.findByText("/home/reader/.cursor/mcp.json")).toBeInTheDocument();
    });

    it("connects one agent from its row and re-reads the state rather than assuming it", async () => {
        routes();
        render(Connect);
        const row = (await screen.findByText("Cursor")).closest("li") as HTMLElement;
        await fireEvent.click(within(row).getByRole("button", { name: "Connect" }));

        // Re-fetched, not patched locally: the server decides what connected
        // means, and it has just looked at the file.
        await vi.waitFor(() => {
            expect(calls().some(([p]) => p === "/api/agent-targets/cursor/connect")).toBe(true);
            expect(calls().filter(([p]) => p === "/api/agent-targets").length).toBe(2);
        });
    });

    it("offers Rewrite on a connected agent and one action only", async () => {
        routes();
        render(Connect);
        const row = (await screen.findByText("Connected")).closest("li") as HTMLElement;
        expect(within(row).getByRole("button", { name: "Rewrite" })).toBeInTheDocument();
        expect(within(row).queryByRole("button", { name: "Connect" })).toBeNull();
        expect(within(row).queryByRole("button", { name: "Update skill" })).toBeNull();
    });

    it("offers to update the skill when the one on disk is older", async () => {
        const targets = structuredClone(TARGETS);
        (targets.targets[0].skill as { stale: boolean }).stale = true;
        routes({ "/api/agent-targets": targets });
        render(Connect);
        const button = await screen.findByRole("button", { name: "Update skill" });
        await fireEvent.click(button);
        await vi.waitFor(() =>
            expect(calls().some(([p]) => p === "/api/agent-targets/claude-code/skill")).toBe(true),
        );
    });

    it("keeps one broken agent from hiding the others", async () => {
        routes({ "/api/agent-targets/cursor/connect": { status: 409, body: "not valid JSON" } });
        render(Connect);
        const row = (await screen.findByText("Cursor")).closest("li") as HTMLElement;
        await fireEvent.click(within(row).getByRole("button", { name: "Connect" }));

        // The row shows the remedy's headline, not the server's body: the
        // body is a 409's technical detail and lives behind the fold (B72).
        expect(await screen.findByText(/already doing this/i)).toBeInTheDocument();
        expect(screen.getAllByText("Claude Code").length).toBeGreaterThan(0);
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
        // The diagnosis is always in stderr (a moved venv, a missing module)
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
        expect(await screen.findByRole("alert")).toBeInTheDocument();
        expect(
            screen.getByText(/bug in Kriko, not something you did/),
        ).toBeInTheDocument();
    });
});
