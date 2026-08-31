import { render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Ask from "./Ask.svelte";

const ROUTES: Record<string, unknown> = {
    "/api/packs": [
        { pack_id: "tools", name: "Tools", version: "0.2.0", enabled: true },
    ],
    "/api/kinds": [{ kind: "product", pack_id: "tools" }],
    "/api/identity-keys/tools": [{ key: "brand" }, { key: "variant" }],
    "/api/packs/tools/vocabulary": {
        context_key: [{ term_id: "usage_hours", unit: "hours" }],
    },
};

describe("Ask", () => {
    it("builds its fields from what the pack declared, not from a hardcoded list", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async (path: string) => {
                // Longest prefix wins: /api/packs/tools/vocabulary also starts
                // with /api/packs, and matching that first would hand the
                // vocabulary call the pack list.
                const key = Object.keys(ROUTES)
                    .filter((r) => path.startsWith(r))
                    .sort((a, b) => b.length - a.length)[0];
                return new Response(JSON.stringify(key ? ROUTES[key] : []));
            }),
        );
        render(Ask);
        expect(await screen.findByLabelText("brand")).toBeInTheDocument();
        expect(await screen.findByLabelText("variant")).toBeInTheDocument();
        expect(await screen.findByLabelText(/usage_hours/)).toBeInTheDocument();
    });

    it("says so when no packs are installed", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => new Response("[]")));
        render(Ask);
        expect(await screen.findByText(/No packs installed/)).toBeInTheDocument();
    });
});
