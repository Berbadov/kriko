import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import Sidebar from "./Sidebar.svelte";

describe("Sidebar", () => {
    it("shows a buyer two group-less destinations and no operator work", () => {
        render(Sidebar, { mode: "buyer" });
        expect(screen.getByRole("link", { name: "New check" })).toBeInTheDocument();
        expect(screen.queryByRole("link", { name: "Coverage" })).toBeNull();
        expect(screen.queryByText("Knowledge")).toBeNull();
    });

    it("shows an author the grouped operator destinations", () => {
        render(Sidebar, { mode: "author" });
        expect(screen.getByText("Knowledge")).toBeInTheDocument();
        expect(screen.getByRole("link", { name: "Overview" })).toBeInTheDocument();
        expect(screen.getByRole("link", { name: "Runs" })).toBeInTheDocument();
    });

    it("carries the mode into every link, so a click does not silently switch it", () => {
        render(Sidebar, { mode: "author" });
        const link = screen.getByRole("link", { name: "Coverage" }) as HTMLAnchorElement;
        expect(link.getAttribute("href")).toContain("mode=author");
    });

    it("offers the mode switch as a labelled group", () => {
        render(Sidebar, { mode: "buyer" });
        expect(screen.getByRole("group", { name: "Mode" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "author" })).toBeInTheDocument();
    });
});
