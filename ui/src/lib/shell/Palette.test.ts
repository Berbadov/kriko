import { render, screen } from "@testing-library/svelte";
import { fireEvent } from "@testing-library/dom";
import { beforeEach, describe, expect, it } from "vitest";
import Palette from "./Palette.svelte";

const press = (key: string, init: KeyboardEventInit = {}) =>
    fireEvent.keyDown(window, { key, ...init });

describe("Palette", () => {
    beforeEach(() => {
        window.location.hash = "";
    });

    it("stays out of the way until a key asks for it", () => {
        render(Palette, { mode: "author" });
        expect(screen.queryByRole("dialog")).toBeNull();
    });

    it("opens on ? and on Ctrl+K, because readers reach for different keys", async () => {
        render(Palette, { mode: "author" });
        await press("?");
        expect(screen.getByRole("dialog", { name: "Go to a screen" })).toBeInTheDocument();
        await press("Escape");
        expect(screen.queryByRole("dialog")).toBeNull();
        await press("k", { ctrlKey: true });
        expect(screen.getByRole("dialog")).toBeInTheDocument();
    });

    it("offers the destinations the rail offers, in this mode", async () => {
        render(Palette, { mode: "buyer" });
        await press("?");
        expect(screen.getByRole("option", { name: /New check/ })).toBeInTheDocument();
        // An author screen is not reachable by name from buyer mode either —
        // the palette is a shortcut through the rail, not a way around it.
        expect(screen.queryByRole("option", { name: /Console/ })).toBeNull();
    });

    it("filters on the group as well as the label", async () => {
        render(Palette, { mode: "author" });
        await press("?");
        const input = screen.getByRole("combobox") as HTMLInputElement;
        await fireEvent.input(input, { target: { value: "console" } });
        expect(screen.getByRole("option", { name: /Console/ })).toBeInTheDocument();
        expect(screen.queryByRole("option", { name: /New check/ })).toBeNull();
    });

    it("says so when nothing matches, and says where the rest went", async () => {
        render(Palette, { mode: "buyer" });
        await press("?");
        await fireEvent.input(screen.getByRole("combobox"), {
            target: { value: "zzzz" },
        });
        expect(screen.getByText(/only exist in author mode/)).toBeInTheDocument();
    });

    it("navigates on Enter and closes", async () => {
        render(Palette, { mode: "author" });
        await press("?");
        await fireEvent.input(screen.getByRole("combobox"), { target: { value: "runs" } });
        await press("Enter");
        expect(window.location.hash).toContain("jobs");
        expect(screen.queryByRole("dialog")).toBeNull();
    });

    it("wraps the cursor rather than sticking at the ends", async () => {
        render(Palette, { mode: "buyer" });
        await press("?");
        const options = screen.getAllByRole("option");
        expect(options[0].getAttribute("aria-selected")).toBe("true");
        await press("ArrowUp");
        const last = screen.getAllByRole("option").at(-1)!;
        expect(last.getAttribute("aria-selected")).toBe("true");
    });

    // Without this, `?` typed into the Console's request body would open the
    // palette over what the reader was writing.
    it("ignores a shortcut key aimed at a text field", async () => {
        render(Palette, { mode: "author" });
        const field = document.createElement("input");
        document.body.append(field);
        await fireEvent.keyDown(field, { key: "?", bubbles: true });
        expect(screen.queryByRole("dialog")).toBeNull();
        field.remove();
    });
});
