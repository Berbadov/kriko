import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import { stubFetch } from "../lib/stub-fetch";
import Settings from "./Settings.svelte";

describe("Settings", () => {
    it("offers no theme choice, because Panel is the only theme", async () => {
        // B159: "Remove all theme selections, keep only the Panel theme". The
        // section and its radios are gone, and nothing on the screen names a
        // palette the reader could pick.
        stubFetch({ "/api/settings": {} });
        render(Settings);
        expect(await screen.findByRole("heading", { name: /Settings/ })).toBeInTheDocument();
        expect(screen.queryByText("Appearance")).toBeNull();
        expect(screen.queryByRole("radio", { name: /lemonade|slate|panel/i })).toBeNull();
        expect(screen.queryByText(/theme/i, { selector: "h3, label, span" })).toBeNull();
    });

    it("offers no mode choice, because there is one mode (B165)", async () => {
        stubFetch({ "/api/settings": { mode: "buyer" } });
        render(Settings);
        expect(await screen.findByRole("heading", { name: /Settings/ })).toBeInTheDocument();
        expect(screen.queryByText("What an answer shows")).toBeNull();
        expect(screen.queryByRole("radio", { name: /buyer|author/i })).toBeNull();
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
