import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Pick from "./Pick.svelte";

/* B158: "A CLI that lists no models says so, rather than showing an empty
 * pick." The reader's LLM pick on Agents, Run and the research cards is this
 * component; the API says why a list is empty and the pick says it. */

const NOTE = "This CLI does not list its models";

describe("Pick", () => {
    it("says a CLI lists no models instead of drawing an empty list", () => {
        render(Pick, { options: [], note: NOTE, emptyLabel: "CLI default" });
        expect(screen.getByText(NOTE)).toBeInTheDocument();
        expect(screen.queryByRole("combobox")).toBeNull();
    });

    it("still lets a name be typed, since the CLI judges the name", async () => {
        const onpick = vi.fn();
        render(Pick, { options: [], note: NOTE, emptyLabel: "CLI default", onpick });
        const field = screen.getByRole("textbox", { name: "Custom name" });
        expect(field).toHaveAttribute("placeholder", "CLI default");
        await fireEvent.change(field, { target: { value: "mistral-large" } });
        expect(onpick).toHaveBeenCalledWith("mistral-large");
    });

    it("draws the list, and no note, when the CLI listed models", () => {
        render(Pick, { options: [{ value: "opus" }], note: "", emptyLabel: "CLI default" });
        expect(screen.getByRole("combobox")).toBeInTheDocument();
        expect(screen.queryByText(NOTE)).toBeNull();
    });

    it("keeps the list when models exist even if a note arrives", () => {
        render(Pick, { options: [{ value: "opus" }], note: NOTE });
        expect(screen.getByRole("combobox")).toBeInTheDocument();
        expect(screen.queryByText(NOTE)).toBeNull();
    });

    it("draws the empty pick as before when nothing says why it is empty", () => {
        render(Pick, { options: [], emptyLabel: "CLI default" });
        expect(screen.getByRole("combobox")).toBeInTheDocument();
    });
});
