import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Analyze from "./Analyze.svelte";

describe("Analyze", () => {
    it("refuses to submit without a URL", async () => {
        const fetchMock = vi.fn();
        vi.stubGlobal("fetch", fetchMock);
        render(Analyze);
        await fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
        expect(await screen.findByText(/URL is required/)).toBeInTheDocument();
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it("reports malformed JSON fields before hitting the API", async () => {
        const fetchMock = vi.fn();
        vi.stubGlobal("fetch", fetchMock);
        render(Analyze);
        await fireEvent.input(screen.getByLabelText("URL"), {
            target: { value: "https://example.invalid/1" },
        });
        await fireEvent.input(screen.getByLabelText(/Raw fields/), {
            target: { value: "{not json" },
        });
        await fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
        expect(await screen.findByText(/must be a JSON object/)).toBeInTheDocument();
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it("explains a 404 as a missing adapter, not as an error", async () => {
        vi.stubGlobal(
            "fetch",
            vi.fn(async () => new Response("no adapter", { status: 404 })),
        );
        render(Analyze);
        await fireEvent.input(screen.getByLabelText("URL"), {
            target: { value: "https://example.invalid/1" },
        });
        await fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
        expect(
            await screen.findByText(/No adapter is installed for this listing/),
        ).toBeInTheDocument();
    });
});
