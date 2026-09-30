import { render, screen } from "@testing-library/svelte";
import { fireEvent } from "@testing-library/dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Palette from "./Palette.svelte";

const press = (key: string, init: KeyboardEventInit = {}) =>
    fireEvent.keyDown(window, { key, ...init });

describe("Palette", () => {
    beforeEach(() => {
        window.location.hash = "";
    });

    it("stays out of the way until a key asks for it", () => {
        render(Palette);
        expect(screen.queryByRole("dialog")).toBeNull();
    });

    it("opens on ? and on Ctrl+K, because readers reach for different keys", async () => {
        render(Palette);
        await press("?");
        expect(screen.getByRole("dialog", { name: "Go to a screen" })).toBeInTheDocument();
        await press("Escape");
        expect(screen.queryByRole("dialog")).toBeNull();
        await press("k", { ctrlKey: true });
        expect(screen.getByRole("dialog")).toBeInTheDocument();
    });

    it("offers every destination the rail offers, and no New check (B163, B165)", async () => {
        render(Palette);
        await press("?");
        expect(screen.getByRole("option", { name: /History/ })).toBeInTheDocument();
        expect(screen.getByRole("option", { name: /Agents/ })).toBeInTheDocument();
        expect(screen.queryByRole("option", { name: /New check/ })).toBeNull();
    });

    it("filters on the group as well as the label", async () => {
        render(Palette);
        await press("?");
        const input = screen.getByRole("combobox") as HTMLInputElement;
        await fireEvent.input(input, { target: { value: "packs" } });
        // Packs is a section of Browse now; the word still finds it.
        expect(screen.getByRole("option", { name: /Browse/ })).toBeInTheDocument();
        expect(screen.queryByRole("option", { name: /History/ })).toBeNull();
    });

    it("finds a merged screen by the name it absorbed", async () => {
        // "Connect" was a rail entry of its own and is a synonym for Agents
        // now. Someone who types the word they remember must land on it —
        // otherwise the reorganisation made the app harder to search than it
        // was, and the reader is punished for having learnt it. See
        // `NavItem.also`.
        render(Palette);
        await press("?");
        await fireEvent.input(screen.getByRole("combobox"), {
            target: { value: "connect" },
        });
        expect(screen.getByRole("option", { name: /Agents/ })).toBeInTheDocument();
    });

    it("says so when nothing matches, without pointing at a mode that no longer exists (B165)", async () => {
        render(Palette);
        await press("?");
        await fireEvent.input(screen.getByRole("combobox"), {
            target: { value: "zzzz" },
        });
        expect(screen.getByText(/No screen called that/)).toBeInTheDocument();
        expect(screen.queryByText(/author/i)).toBeNull();
    });

    it("navigates on Enter and closes", async () => {
        render(Palette);
        await press("?");
        await fireEvent.input(screen.getByRole("combobox"), { target: { value: "runs" } });
        await press("Enter");
        // The destination, not the retired name it was found by: `runs` is a
        // lens on Activity, and the address is the screen.
        expect(window.location.hash).toContain("activity");
        expect(screen.queryByRole("dialog")).toBeNull();
    });

    // shell-8: "browse" is a substring of both "Browse" and "Browser
    // extension" — an unranked filter left them in table order, and Enter
    // opened whichever came first in NAV rather than the exact label match.
    it("ranks an exact label match ahead of one that only starts the same way", async () => {
        render(Palette);
        await press("?");
        await fireEvent.input(screen.getByRole("combobox"), {
            target: { value: "browse" },
        });
        const options = screen.getAllByRole("option");
        expect(options[0]).toHaveTextContent("Browse");
    });

    // shell-8: go() used to call navigate(), which copies the *entire*
    // current query string into the destination — an id= left over from
    // History followed the reader into whatever screen they picked next.
    it("carries nothing from the current screen into the destination, not its own query", async () => {
        window.location.hash = "#/history?lens=old&id=abc123";
        render(Palette);
        await press("?");
        await fireEvent.input(screen.getByRole("combobox"), {
            target: { value: "packs" },
        });
        await press("Enter");
        expect(window.location.hash).toBe("#/knowledge");
    });

    it("wraps the cursor rather than sticking at the ends", async () => {
        render(Palette);
        await press("?");
        const options = screen.getAllByRole("option");
        expect(options[0].getAttribute("aria-selected")).toBe("true");
        await press("ArrowUp");
        const last = screen.getAllByRole("option").at(-1)!;
        expect(last.getAttribute("aria-selected")).toBe("true");
    });

    // shell-7: the list is capped at 45vh, which is well under the full
    // option count at a short window — arrow keys moved the highlight past
    // the visible area with nothing to bring it back into view.
    it("scrolls the highlighted option into view as the cursor moves", async () => {
        // jsdom has no layout engine, so scrollIntoView is not implemented at
        // all; the call itself, guarded so its absence never throws, is what
        // this asserts.
        const spy = vi.fn();
        (HTMLElement.prototype as { scrollIntoView?: () => void }).scrollIntoView = spy;
        render(Palette);
        await press("?");
        spy.mockClear();
        await press("ArrowDown");
        expect(spy).toHaveBeenCalledWith({ block: "nearest" });
    });

    // Without this, `?` typed into any note or search box would open the
    // palette over what the reader was writing.
    it("ignores a shortcut key aimed at a text field", async () => {
        render(Palette);
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
        render(Palette);
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
        render(Palette);
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
