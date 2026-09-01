import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Coverage from "./Coverage.svelte";

const PACK = {
    pack_id: "tools",
    name: "Tools",
    version: "0.2.0",
    enabled: true,
    subjects: 4,
    claims: 9,
    evidence: 12,
    digest: "abc123",
};

const CONFIG = {
    server_name: "kriko",
    frozen: true,
    store: "/home/reader/.kriko/knowledge.sqlite",
    mcp_json: {
        mcpServers: {
            kriko: {
                type: "stdio",
                command: "/opt/Kriko/kriko-sidecar",
                args: ["--mcp", "--store", "/home/reader/.kriko/knowledge.sqlite"],
            },
        },
    },
    tools: ["research_brief", "coverage_gaps", "submit_findings"],
};

const routes = (gaps: unknown[]) =>
    vi.fn(async (path: string) => {
        const url = String(path);
        if (url === "/api/packs") return new Response(JSON.stringify([PACK]));
        if (url === "/api/agent-config") return new Response(JSON.stringify(CONFIG));
        if (url.includes("/gaps")) return new Response(JSON.stringify(gaps));
        return new Response("no route", { status: 404 });
    });

describe("Coverage", () => {
    it("says the free plane writes a brief rather than gathering", async () => {
        // The button used to look like it did the research. A reader pressing it
        // and getting a brief with no explanation reads that as a broken button.
        vi.stubGlobal("fetch", routes([]));
        render(Coverage);
        expect(await screen.findByText(/writes a/)).toBeInTheDocument();
        expect(screen.getByText(/does not gather anything itself/)).toBeInTheDocument();
    });

    it("hands over a config that names this window's own store", async () => {
        vi.stubGlobal("fetch", routes([]));
        render(Coverage);
        await fireEvent.click(await screen.findByText("Connect an agent"));
        // The store path is the whole point: an agent on a different SQLite
        // file writes findings nobody ever sees, with no error in between.
        // findAllByText: the path is shown twice on purpose — in the prose that
        // says which store this is, and inside the block being copied.
        expect(
            (await screen.findAllByText(/home\/reader\/\.kriko\/knowledge\.sqlite/))
                .length,
        ).toBeGreaterThan(1);
        expect(screen.getByText(/--mcp/)).toBeInTheDocument();
    });

    it("still lists gaps and starts a job for one", async () => {
        const fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
            const url = String(path);
            if (url === "/api/packs") return new Response(JSON.stringify([PACK]));
            if (url.includes("/gaps"))
                return new Response(
                    JSON.stringify([
                        { subject_id: "s1", label: "A subject", kind: "product" },
                    ]),
                );
            if (url === "/api/research" && init?.method === "POST")
                return new Response(JSON.stringify({ job_id: "j1" }));
            if (url.startsWith("/api/jobs/j1"))
                return new Response(
                    JSON.stringify({
                        job_id: "j1",
                        state: "running",
                        message: "working",
                        done: false,
                    }),
                );
            return new Response("no route", { status: 404 });
        });
        vi.stubGlobal("fetch", fetchMock);
        render(Coverage);
        // By role, not by text: the card above names the button in its prose,
        // and a text match would click the <em> and silently do nothing.
        await fireEvent.click(
            await screen.findByRole("button", { name: "Research" }),
        );
        expect(await screen.findByText("working")).toBeInTheDocument();
    });
});
