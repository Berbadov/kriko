import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Packs from "./Packs.svelte";

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

describe("Packs", () => {
    it("lists an installed pack with its counts", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify([PACK]))));
        render(Packs);
        expect(await screen.findByText("Tools")).toBeInTheDocument();
        expect(await screen.findByText(/4 subjects · 9 claims/)).toBeInTheDocument();
    });

    it("shows what the index offers and starts an update", async () => {
        const started: string[] = [];
        const fetchMock = vi.fn(async (path: string, init?: RequestInit) => {
            const url = String(path);
            if (url.startsWith("/api/packs/updates"))
                return new Response(
                    JSON.stringify({
                        index_url: "https://example.invalid/packs.json",
                        error: null,
                        packs: [
                            {
                                pack_id: "tools",
                                name: "Tools",
                                installed_version: "0.2.0",
                                offered_version: "0.3.0",
                                state: "available",
                                reason: "0.2.0 → 0.3.0",
                            },
                        ],
                    }),
                );
            if (url === "/api/packs/update") {
                started.push(String(init?.body));
                return new Response(JSON.stringify({ job_id: "j1", kind: "pack_update" }));
            }
            if (url.startsWith("/api/jobs/"))
                return new Response(
                    JSON.stringify({
                        job_id: "j1",
                        state: "succeeded",
                        message: "updated 1 pack(s)",
                        done: true,
                    }),
                );
            return new Response(JSON.stringify([PACK]));
        });
        vi.stubGlobal("fetch", fetchMock);
        vi.stubGlobal("EventSource", undefined);
        render(Packs);
        await fireEvent.click(
            await screen.findByRole("button", { name: "Check for updates" }),
        );
        expect(await screen.findByText("0.2.0 → 0.3.0")).toBeInTheDocument();
        await fireEvent.click(await screen.findByRole("button", { name: "Update" }));
        expect(await screen.findByText(/updated 1 pack/)).toBeInTheDocument();
        expect(started[0]).toContain("tools");
    });

    it("says the index is unreachable rather than looking broken", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async (path: string) =>
                String(path).startsWith("/api/packs/updates")
                    ? new Response(
                          JSON.stringify({
                              index_url: "u",
                              error: "URLError: refused",
                              packs: [],
                          }),
                      )
                    : new Response(JSON.stringify([PACK])),
            ),
        );
        render(Packs);
        await fireEvent.click(
            await screen.findByRole("button", { name: "Check for updates" }),
        );
        expect(
            await screen.findByText(/Could not reach the pack index/),
        ).toBeInTheDocument();
    });

    it("refuses to install with no file chosen", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => new Response("[]")));
        render(Packs);
        await fireEvent.click(await screen.findByRole("button", { name: "Install pack" }));
        expect(await screen.findByText(/Choose a .kpack file first/)).toBeInTheDocument();
    });
});
