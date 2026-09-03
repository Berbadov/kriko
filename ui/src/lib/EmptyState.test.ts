import { render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import EmptyState from "./EmptyState.svelte";

describe("EmptyState", () => {
    it("says what is empty and why it matters", () => {
        render(EmptyState, {
            title: "Nothing asked yet",
            detail: "Checks you run show up here.",
        });
        expect(screen.getByText("Nothing asked yet")).toBeInTheDocument();
        expect(screen.getByText("Checks you run show up here.")).toBeInTheDocument();
    });

    it("offers a link when the next step is somewhere else", () => {
        render(EmptyState, {
            title: "No packs",
            actionLabel: "Open Packs",
            actionHref: "#/packs",
        });
        const link = screen.getByRole("link", { name: "Open Packs" }) as HTMLAnchorElement;
        expect(link.getAttribute("href")).toBe("#/packs");
    });

    it("offers a button when the next step is right here", async () => {
        const onAction = vi.fn();
        render(EmptyState, {
            title: "No packs",
            actionLabel: "Check for updates",
            onAction,
        });
        screen.getByRole("button", { name: "Check for updates" }).click();
        expect(onAction).toHaveBeenCalledOnce();
    });

    it("renders no action when there is nothing useful to offer", () => {
        render(EmptyState, { title: "Nothing here" });
        expect(screen.queryByRole("button")).toBeNull();
        expect(screen.queryByRole("link")).toBeNull();
    });
});
