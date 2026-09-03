import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import { stubFetch } from "../lib/stub-fetch";
import Subjects from "./Subjects.svelte";

describe("Subjects", () => {
    it("lists subjects and re-queries as you type", async () => {
        const fetchMock = vi.fn(
            async (_path: string) =>
                new Response(
                    JSON.stringify([
                        {
                            label: "Bench Grinder 8in",
                            kind: "product",
                            pack_id: "tools",
                            claims: 3,
                        },
                    ]),
                ),
        );
        vi.stubGlobal("fetch", fetchMock);
        render(Subjects);
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

    it("says what to type when the search finds nothing", async () => {
        stubFetch({ "/api/subjects": [] });
        render(Subjects);
        expect(await screen.findByText(/No matching subjects/)).toBeInTheDocument();
        expect(await screen.findByText(/coverage is not there yet/)).toBeInTheDocument();
    });
});
