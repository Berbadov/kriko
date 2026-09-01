import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Check from "./Check.svelte";

const ROUTES: Record<string, unknown> = {
    "/api/packs/tools/vocabulary": {
        context_key: [{ term_id: "usage_hours", unit: "hours" }],
    },
    "/api/packs": [{ pack_id: "tools", name: "Tools", enabled: true }],
    "/api/adapters": [
        { id: "a1", site: "example.test", pack_id: "tools", match: [], labels: [] },
    ],
    "/api/kinds": [{ kind: "product", pack_id: "tools" }],
    "/api/identity-keys/tools": [
        { key: "brand", match_json: '{"required": true}' },
        { key: "model", match_json: "{}" },
    ],
    "/api/subjects": [
        { subject_id: "s1", label: "Makita DHP484", kind: "product", pack_id: "tools", claims: 3 },
    ],
    "/api/subjects/s1": {
        subject_id: "s1",
        pack_id: "tools",
        kind: "product",
        label: "Makita DHP484",
        attributes: [
            { key: "brand", value_text: "makita", unit: "", is_identity: 1 },
            { key: "model", value_text: "DHP484", unit: "", is_identity: 1 },
        ],
        relations: [],
        claims: [],
    },
};

/** Longest matching prefix wins — `/api/packs` would otherwise swallow
 * `/api/packs/tools/vocabulary`. */
function stub(overrides: Record<string, unknown> = {}, status = 200) {
    const table = { ...ROUTES, ...overrides };
    return vi.fn(async (path: string) => {
        const key = Object.keys(table)
            .filter((k) => path.startsWith(k))
            .sort((a, b) => b.length - a.length)[0];
        if (!key) return new Response("not found", { status: 404 });
        const value = table[key];
        if (value instanceof Response) return value.clone();
        return new Response(JSON.stringify(value), { status });
    });
}

describe("Check", () => {
    it("builds its guided form from the pack's own vocabulary", async () => {
        vi.stubGlobal("fetch", stub());
        render(Check);
        // Neither field name appears in this component's source; both are read
        // off /api/identity-keys and /api/packs/{id}/vocabulary at runtime.
        expect(await screen.findByLabelText(/brand/)).toBeInTheDocument();
        expect(await screen.findByLabelText(/usage_hours/)).toBeInTheDocument();
    });

    it("refuses to ask until the pack's required identity is filled in", async () => {
        vi.stubGlobal("fetch", stub());
        render(Check);
        const ask = await screen.findByRole("button", {
            name: /what goes wrong/i,
        });
        expect(ask).toBeDisabled();
        await fireEvent.input(await screen.findByLabelText(/brand/), {
            target: { value: "makita" },
        });
        expect(ask).not.toBeDisabled();
    });

    it("fills the form from an installed subject rather than asking for spellings", async () => {
        vi.stubGlobal("fetch", stub());
        render(Check);
        await fireEvent.input(await screen.findByLabelText(/already knows/i), {
            target: { value: "makita" },
        });
        await fireEvent.click(await screen.findByRole("button", { name: /DHP484/ }));
        expect((await screen.findByLabelText(/model/)) as HTMLInputElement).toHaveValue(
            "DHP484",
        );
    });

    it("names the sites it can read when the pasted host is not one", async () => {
        vi.stubGlobal(
            "fetch",
            stub({ "/api/analyze": new Response("no adapter", { status: 404 }) }),
        );
        render(Check);
        await fireEvent.input(await screen.findByLabelText(/web address/i), {
            target: { value: "https://unknown.test/x" },
        });
        await fireEvent.click(
            await screen.findByRole("button", { name: /check this listing/i }),
        );
        expect(await screen.findByText(/No installed pack can read that site/))
            .toBeInTheDocument();
        expect(await screen.findByText(/example.test/)).toBeInTheDocument();
    });

    it("offers the scraped-fields editor only in author mode, and never as JSON", async () => {
        vi.stubGlobal("fetch", stub());
        const { unmount } = render(Check, { props: { mode: "buyer" } });
        expect(screen.queryByText(/Page fields/)).not.toBeInTheDocument();
        unmount();
        render(Check, { props: { mode: "author" } });
        expect(await screen.findByText(/Page fields/)).toBeInTheDocument();
        expect(screen.queryByLabelText(/JSON/i)).not.toBeInTheDocument();
    });
});
