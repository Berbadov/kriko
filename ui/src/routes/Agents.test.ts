import { render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Agents from "./Agents.svelte";

/* Agents is Connect now — Connect keeps its own suite, so what is asserted
 * here is just that this screen still delegates to it rather than to the
 * Console lens it used to also offer. */

function stub() {
    vi.stubGlobal(
        "fetch",
        vi.fn(
            async (path: string) =>
                new Response(
                    JSON.stringify(
                        String(path).includes("/api/packs")
                            ? []
                            : String(path).includes("agent-targets")
                              ? { targets: [] }
                              : String(path).includes("agent-skill")
                                ? { name: "kriko-research", body: "", packs: [] }
                                : { mcp_json: {}, items: [], packs: [] },
                    ),
                ),
        ),
    );
}

describe("Agents", () => {
    it("renders Connect and nothing else", async () => {
        stub();
        render(Agents, {});
        expect(await screen.findByRole("heading", { name: /Connect/i })).toBeInTheDocument();
        expect(screen.queryByRole("tablist", { name: "Agents" })).toBeNull();
        expect(screen.queryByRole("heading", { name: "Console" })).toBeNull();
    });
});
