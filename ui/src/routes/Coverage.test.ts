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

    it("points at the screen that wires an agent, rather than wiring one here", async () => {
        // Connecting writes files on this machine. That is not something to do
        // from a button on a report; the report's job is to say the next step
        // exists and where it lives.
        vi.stubGlobal("fetch", routes([]));
        render(Coverage);
        const link = await screen.findByText("Connect an agent");
        expect(link.getAttribute("href")).toContain("connect");
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
