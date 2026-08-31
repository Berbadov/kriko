import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Browse from "./Browse.svelte";

describe("Browse", () => {
    it("lists subjects and re-queries as you type", async () => {
        const fetchMock = vi.fn(
            async () =>
                new Response(
                    JSON.stringify([
                        { label: "Bench Grinder 8in", kind: "product", pack_id: "tools", claims: 3 },
                    ]),
                ),
        );
        vi.stubGlobal("fetch", fetchMock);
        render(Browse);
        expect(await screen.findByText("Bench Grinder 8in")).toBeInTheDocument();

        await fireEvent.input(screen.getByLabelText("Search subjects"), {
            target: { value: "grinder" },
        });
        await waitFor(() =>
            expect(
                fetchMock.mock.calls.some(([path]) => String(path).includes("q=grinder")),
            ).toBe(true),
        );
    });

    it("says so when nothing matches", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => new Response("[]")));
        render(Browse);
        expect(await screen.findByText(/No matching subjects/)).toBeInTheDocument();
    });
});
