import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import Jobs from "../../routes/Jobs.svelte";
import { parseHash } from "../router";
import Sidebar from "./Sidebar.svelte";
import { readings, unwatch, EMPTY } from "./instruments";

/* The rail starts its own clock on mount. Stopped here so one test's poll
 * cannot land in the next one's assertions, and the store reset so a figure
 * set by one test does not leak into a rail that should have none. */
afterEach(() => {
    unwatch();
    readings.set(EMPTY);
});

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

describe("the rail's primary action", () => {
    it("gives an author the one action that makes knowledge, outside the list of places", () => {
        render(Sidebar, { mode: "author" });
        const action = screen.getByRole("link", { name: /Start a new pack/ });
        expect(action).toBeInTheDocument();
        expect(parseHash(action.getAttribute("href") ?? "")).toEqual({
            name: "jobs",
            params: [],
            query: { mode: "author", author: "new" },
        });
        // Outside `.rail-nav` on purpose: a rail lists where you are, and this
        // is a do. Inside it, it reads as the fourteenth destination.
        expect(action.closest("nav")).toBeNull();
    });

    it("does not offer it to a buyer, who has no screen behind it", () => {
        render(Sidebar, { mode: "buyer" });
        expect(screen.queryByRole("link", { name: /Start a new pack/ })).toBeNull();
    });
});

describe("the new-pack destination", () => {
    function at(hash: string) {
        window.history.replaceState(null, "", hash);
        window.dispatchEvent(new HashChangeEvent("hashchange"));
    }

    afterEach(() => {
        window.history.replaceState(null, "", "#/check");
    });

    it("opens and focuses authoring on arrival, without starting work", async () => {
        const fetchMock = vi.fn(async (_path: string, _init?: RequestInit) =>
            new Response(JSON.stringify({ items: [] })),
        );
        vi.stubGlobal("fetch", fetchMock);
        render(Sidebar, { mode: "author" });
        at(screen.getByRole("link", { name: /Start a new pack/ }).getAttribute("href")!);
        render(Jobs);
        const input = screen.getByLabelText("What is the category?");
        await waitFor(() => expect(input).toHaveFocus());
        expect(input.closest("details")).toHaveAttribute("open");
        expect(parseHash(window.location.hash).query).toEqual({ mode: "author" });
        expect(fetchMock.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
    });

    it("reopens the form on the same route without clearing a draft", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ items: [] }))));
        at("#/jobs?mode=author");
        render(Sidebar, { mode: "author" });
        render(Jobs);
        const input = screen.getByLabelText("What is the category?");
        expect(input.closest("details")).not.toHaveAttribute("open");
        const action = screen.getByRole("link", { name: /Start a new pack/ });
        at(action.getAttribute("href")!);
        await waitFor(() => expect(input).toHaveFocus());
        await fireEvent.input(input, { target: { value: "espresso machines" } });
        input.closest("details")!.open = false;
        action.focus();
        at(action.getAttribute("href")!);
        await waitFor(() => expect(input).toHaveFocus());
        expect(input.closest("details")).toHaveAttribute("open");
        expect(input).toHaveValue("espresso machines");
    });
});

describe("the rail's figures", () => {
    it("carries the claim count on the row that browses them", () => {
        readings.set({ ...EMPTY, claims: 1620 });
        render(Sidebar, { mode: "author" });
        expect(screen.getByTitle(/1,620 claims/)).toBeInTheDocument();
    });

    it("says nothing on any row until something has been read", () => {
        render(Sidebar, { mode: "author" });
        // Not "renders a zero" — an unread figure and a figure that is zero
        // are different claims and the rail may only make the second one.
        expect(screen.queryByTitle(/claims across/)).toBeNull();
        expect(screen.queryByTitle(/jobs running/)).toBeNull();
    });

    it("leaves every other row exactly as it was", () => {
        readings.set({ ...EMPTY, claims: 3, running: 1, spentUsd: 0.5 });
        render(Sidebar, { mode: "author" });
        // Three figures, fourteen rows. A number on every row is a dashboard.
        expect(screen.getAllByTitle(/claims across|jobs? running|spent on research/))
            .toHaveLength(3);
    });
});
