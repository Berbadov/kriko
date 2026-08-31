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

    it("refuses to install with no file chosen", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => new Response("[]")));
        render(Packs);
        await fireEvent.click(await screen.findByRole("button", { name: "Install pack" }));
        expect(await screen.findByText(/Choose a .kpack file first/)).toBeInTheDocument();
    });
});
