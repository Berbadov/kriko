import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import { stubFetch } from "../lib/stub-fetch";
import { mode } from "../lib/mode";
import Settings from "./Settings.svelte";

describe("Settings", () => {
    it("offers no theme choice, because Panel is the only theme", async () => {
        // B159: "Remove all theme selections, keep only the Panel theme". The
        // section and its radios are gone, and nothing on the screen names a
        // palette the reader could pick.
        stubFetch({ "/api/settings": {} });
        render(Settings);
        expect(await screen.findByText("What an answer shows")).toBeInTheDocument();
        expect(screen.queryByText("Appearance")).toBeNull();
        expect(screen.queryByRole("radio", { name: /lemonade|slate|panel/i })).toBeNull();
        expect(screen.queryByText(/theme/i, { selector: "h3, label, span" })).toBeNull();
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

    it("draws a chosen option as a marked card", async () => {
        // The card is the shared `.choice` (components.css), raised like a
        // button; what the screen owes it is the `on` class on the chosen one.
        stubFetch({ "/api/settings": {} });
        mode.set("buyer");
        render(Settings);
        const buyer = (await screen.findByRole("radio", { name: /buyer/i })).closest("label");
        expect(buyer).toHaveClass("choice", "on");
        expect(screen.getByRole("radio", { name: /author/i }).closest("label")).not.toHaveClass("on");
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
