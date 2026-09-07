import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import { stubFetch } from "../lib/stub-fetch";
import { applyTheme } from "../lib/theme";
import { mode } from "../lib/mode";
import Settings from "./Settings.svelte";

describe("Settings", () => {
    it("offers every theme and marks the live one", async () => {
        stubFetch({ "/api/settings": {} });
        applyTheme("lemonade");
        render(Settings);
        expect(await screen.findByRole("radio", { name: /lemonade/i })).toBeChecked();
        expect(screen.getByRole("radio", { name: /slate/i })).not.toBeChecked();
    });

    it("repaints the app the moment a theme is picked", async () => {
        stubFetch({ "/api/settings": {} });
        applyTheme("slate");
        render(Settings);
        await fireEvent.click(await screen.findByRole("radio", { name: /lemonade/i }));
        expect(document.documentElement.dataset.theme).toBe("lemonade");
    });

    it("remembers the choice rather than only painting it", async () => {
        const fetchMock = vi.fn(async (_path: string) => new Response(JSON.stringify({})));
        vi.stubGlobal("fetch", fetchMock);
        applyTheme("slate");
        render(Settings);
        await fireEvent.click(await screen.findByRole("radio", { name: /lemonade/i }));
        await waitFor(() =>
            expect(
                fetchMock.mock.calls.some(([path]) => String(path).includes("/api/settings")),
            ).toBe(true),
        );
    });

    it("switches which half of an answer gets drawn", async () => {
        stubFetch({ "/api/settings": {} });
        mode.set("buyer");
        render(Settings);
        await fireEvent.click(await screen.findByRole("radio", { name: /author/i }));
        let seen = "";
        mode.subscribe((value) => (seen = value))();
        expect(seen).toBe("author");
    });

    it("prints everything it keeps, because a local app owes that answer plainly", async () => {
        stubFetch({ "/api/settings": { theme: "panel", mode: "author" } });
        render(Settings);
        expect(await screen.findByText("theme")).toBeInTheDocument();
        expect(screen.getByText('"author"')).toBeInTheDocument();
    });

    it("says nothing is stored yet rather than showing an empty list", async () => {
        stubFetch({ "/api/settings": {} });
        render(Settings);
        expect(await screen.findByText(/Nothing yet/)).toBeInTheDocument();
    });
});
