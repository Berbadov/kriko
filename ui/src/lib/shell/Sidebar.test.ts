import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import Sidebar from "./Sidebar.svelte";

describe("Sidebar", () => {
    it("shows a buyer two group-less destinations and no operator work", () => {
        render(Sidebar, { mode: "buyer" });
        expect(screen.getByRole("link", { name: "New check" })).toBeInTheDocument();
        expect(screen.queryByRole("link", { name: "Browse" })).toBeNull();
        expect(screen.queryByText("Knowledge")).toBeNull();
    });

    it("shows an author the grouped operator destinations", () => {
        render(Sidebar, { mode: "author" });
        expect(screen.getByText("Knowledge")).toBeInTheDocument();
        expect(screen.getByRole("link", { name: "Overview" })).toBeInTheDocument();
        expect(screen.getByRole("link", { name: "Activity" })).toBeInTheDocument();
        expect(screen.getByRole("link", { name: "Agents" })).toBeInTheDocument();
        // The five rows those two replaced are gone from the rail — the point
        // of the merge was the rail, not the screens.
        expect(screen.queryByRole("link", { name: "Runs" })).toBeNull();
        expect(screen.queryByRole("link", { name: "Console" })).toBeNull();
    });

    it("carries the mode into every link, so a click does not silently switch it", () => {
        render(Sidebar, { mode: "author" });
        const link = screen.getByRole("link", { name: "Browse" }) as HTMLAnchorElement;
        expect(link.getAttribute("href")).toContain("mode=author");
    });

    it("offers the mode switch as a labelled group", () => {
        render(Sidebar, { mode: "buyer" });
        expect(screen.getByRole("group", { name: "Mode" })).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "author" })).toBeInTheDocument();
    });
});

describe("the rail's current row", () => {
    /** Set the address before render: `route` re-reads the hash on subscribe. */
    function at(hash: string) {
        window.location.hash = hash;
    }

    it("marks the row for the route", () => {
        at("#/packs?mode=author");
        render(Sidebar, { mode: "author" });
        expect(screen.getByRole("link", { name: "Packs" })).toHaveAttribute(
            "aria-current",
            "page",
        );
    });

    it("marks the row a retired route actually renders", () => {
        // `#/coverage` is a link the browser extension hands out; it renders
        // Knowledge's gaps lens. The rail used to compare the raw route name
        // against its own rows, match nothing, and light no row at all —
        // arriving from the extension looked like arriving nowhere.
        at("#/coverage?mode=author");
        render(Sidebar, { mode: "author" });
        expect(screen.getByRole("link", { name: "Browse" })).toHaveAttribute(
            "aria-current",
            "page",
        );
    });

    it("gives every row its name, which is what the marker is measured from", () => {
        at("#/check");
        render(Sidebar, { mode: "buyer" });
        expect(screen.getByRole("link", { name: "New check" })).toHaveAttribute(
            "data-route",
            "check",
        );
    });
});
