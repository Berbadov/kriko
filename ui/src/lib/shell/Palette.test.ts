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
        expect(screen.queryByRole("option", { name: /Agents/ })).toBeNull();
    });

    it("filters on the group as well as the label", async () => {
        render(Palette, { mode: "author" });
        await press("?");
        const input = screen.getByRole("combobox") as HTMLInputElement;
        await fireEvent.input(input, { target: { value: "packs" } });
        expect(screen.getByRole("option", { name: /Packs/ })).toBeInTheDocument();
        expect(screen.queryByRole("option", { name: /New check/ })).toBeNull();
    });

    it("finds a merged screen by the name it absorbed", async () => {
        // "Console" was a rail entry for six versions and is a lens on Agents
        // now. Someone who types the word they remember must land on it —
        // otherwise the reorganisation made the app harder to search than it
        // was, and the reader is punished for having learnt it. See
        // `NavItem.also`.
        render(Palette, { mode: "author" });
        await press("?");
        await fireEvent.input(screen.getByRole("combobox"), {
            target: { value: "console" },
        });
        expect(screen.getByRole("option", { name: /Agents/ })).toBeInTheDocument();
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
        // The destination, not the retired name it was found by: `runs` is a
        // lens on Activity, and the address is the screen.
        expect(window.location.hash).toContain("activity");
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

    /* B74: `aria-modal="true"` was a claim the dialog did not keep.
     *
     * Tab from the last option walked straight out into the rail behind the
     * scrim — focus on a link the reader cannot see, no visible ring anywhere
     * on screen, and nothing but Escape (which they now have no reason to
     * think is listening) to get back. A modal that says it is modal has to
     * hold the tab order, or it should not say so.
     */
    it("holds the tab order it claims to hold", async () => {
        render(Palette, { mode: "author" });
        await press("?");
        const stops = [
            screen.getByRole("combobox"),
            ...screen.getAllByRole("option").map((li) => li.querySelector("button")!),
        ];
        stops[stops.length - 1].focus();
        await fireEvent.keyDown(stops[stops.length - 1], { key: "Tab" });
        expect(document.activeElement).toBe(stops[0]);

        stops[0].focus();
        await fireEvent.keyDown(stops[0], { key: "Tab", shiftKey: true });
        expect(document.activeElement).toBe(stops[stops.length - 1]);
    });

    it("leaves an ordinary Tab inside the dialog alone", async () => {
        // Trapping means wrapping at the ends, not intercepting every press:
        // a handler that preventDefaults each Tab leaves the middle of the
        // list unwalkable, which is the same bug facing the other way.
        render(Palette, { mode: "author" });
        await press("?");
        const input = screen.getByRole("combobox");
        input.focus();
        const event = new KeyboardEvent("keydown", {
            key: "Tab", bubbles: true, cancelable: true,
        });
        input.dispatchEvent(event);
        expect(event.defaultPrevented).toBe(false);
    });
});
