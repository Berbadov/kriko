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
        expect(screen.getByText("Verify the connection")).toBeInTheDocument();
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

    it("is one row per agent: a mark, a state, a model, an effort and one action", async () => {
        routes();
        render(Connect);
        const row = (await screen.findByText("Connected")).closest("li") as HTMLElement;
        expect(row.querySelector(".mark")).not.toBeNull();
        expect(within(row).getByText("Connected")).toBeInTheDocument();
        expect(within(row).getByText("LLM")).toBeInTheDocument();
        expect(within(row).getByText("Effort")).toBeInTheDocument();
        expect(within(row).getAllByRole("button")).toHaveLength(1);
    });

    it("carries none of the explanatory paragraphs it used to", async () => {
        routes();
        render(Connect);
        await screen.findByText("Your agents");
        for (const gone of [
            /Lists are what each CLI reported/,
            /Starts the command the config names/,
            /Anything that speaks MCP works/,
            /used when a run does not name one/,
        ]) {
            expect(screen.queryByText(gone)).toBeNull();
        }
    });

    const VERIFIED = {
        ok: true, server: "kriko", tools: ["research_brief"],
        steps: [
            { id: "start", state: "ok" },
            { id: "initialize", state: "ok" },
            { id: "tools", state: "ok" },
        ],
        log: "$ kriko --mcp\nstart: ok\nserver: kriko",
    };

    it("shows each verify step's result and keeps the log until asked", async () => {
        routes({ "/api/agent-verify": VERIFIED });
        render(Connect);
        await fireEvent.click(await screen.findByRole("button", { name: "Verify" }));
        // The verdict lands on its own tick, so the step rows exist before
        // their state words do: wait for the state, not the list. Asserting
        // on the list alone raced the fetch and flaked.
        expect((await screen.findAllByText("Passed")).length).toBeGreaterThan(0);
        const steps = screen.getByRole("list", { name: "Verify steps" });
        expect(within(steps).getAllByRole("listitem")).toHaveLength(3);
        expect(within(steps).getByText("Start the command")).toBeInTheDocument();
        expect(within(steps).getAllByText("Passed")).toHaveLength(3);
        // On request only.
        expect(screen.queryByText(/start: ok/)).toBeNull();
        await fireEvent.click(screen.getByRole("button", { name: "Show log" }));
        expect(await screen.findByText(/start: ok/)).toBeInTheDocument();
        await fireEvent.click(screen.getByRole("button", { name: "Hide log" }));
        expect(screen.queryByText(/start: ok/)).toBeNull();
    });

    it("marks the step that failed, and the ones after it as not run", async () => {
        // The diagnosis is always in stderr (a moved venv, a missing module)
        // and it is the one thing a reader never otherwise sees, now behind
        // Show log instead of a block that pushed the page down.
        routes({ "/api/agent-verify": {
            ok: false, detail: "ModuleNotFoundError: No module named 'fastapi'",
            steps: [
                { id: "start", state: "ok" },
                { id: "initialize", state: "failed" },
                { id: "tools", state: "skipped" },
            ],
            log: "$ kriko --mcp\nModuleNotFoundError: No module named 'fastapi'",
        } });
        render(Connect);
        await fireEvent.click(await screen.findByRole("button", { name: "Verify" }));
        expect(await screen.findByText("Failed")).toBeInTheDocument();
        const steps = screen.getByRole("list", { name: "Verify steps" });
        expect(within(steps).getByText("Not run")).toBeInTheDocument();
        expect(screen.queryByText(/ModuleNotFoundError/)).toBeNull();
        await fireEvent.click(screen.getByRole("button", { name: "Show log" }));
        expect(await screen.findByText(/ModuleNotFoundError/)).toBeInTheDocument();
    });

    it("still says something when the request itself failed", async () => {
        routes({ "/api/agent-verify": { status: 500, body: "boom" } });
        render(Connect);
        await fireEvent.click(await screen.findByRole("button", { name: "Verify" }));
        expect(await screen.findByText("Failed")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Show log" })).toBeInTheDocument();
    });

    it("shows how to connect another harness as steps with states, not prose", async () => {
        routes();
        render(Connect);
        const steps = await screen.findByRole("list", { name: "Connect another harness" });
        const items = within(steps).getAllByRole("listitem");
        expect(items).toHaveLength(3);
        expect(within(items[0]).getByText("Copy the config block")).toBeInTheDocument();
        expect(items[0].querySelector("[data-state]")?.getAttribute("data-state")).toBe("todo");
        await fireEvent.click(within(items[0]).getByRole("button", { name: "Copy" }));
        await vi.waitFor(() =>
            expect(items[0].querySelector("[data-state]")?.getAttribute("data-state")).not.toBe("todo"),
        );
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
