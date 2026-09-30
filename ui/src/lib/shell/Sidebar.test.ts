import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import { stubFetch } from "../stub-fetch";
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
    it("shows a buyer the two groups they can use and no operator work", () => {
        render(Sidebar, { mode: "buyer" });
        expect(screen.getByRole("link", { name: "New check" })).toBeInTheDocument();
        expect(screen.queryByRole("link", { name: "Browse" })).toBeNull();
        expect(screen.queryByText("Knowledge")).toBeNull();
        expect(screen.getByText("Check")).toBeInTheDocument();
        expect(screen.getByText("This install")).toBeInTheDocument();
    });

    it("gives every group title a symbol, and no title is only letters", () => {
        // B159: "Use symbols for sections". A group in the rail used to be a
        // run of rows, or (for the author-only two) a bare word in capitals.
        for (const shown of ["buyer", "author"] as const) {
            const { container, unmount } = render(Sidebar, { mode: shown });
            const titles = container.querySelectorAll(".nav-title");
            expect(titles.length).toBe(shown === "buyer" ? 2 : 4);
            for (const title of titles) {
                const symbol = title.querySelector("svg");
                expect(symbol, `${title.textContent?.trim()} has no symbol`).not.toBeNull();
                // A symbol that failed to draw is an empty box, not a glyph.
                expect(symbol?.querySelectorAll("path").length).toBeGreaterThan(0);
            }
            unmount();
        }
    });

    it("draws the brand mark from the smooth drawing, not the pixel grid", () => {
        // B161: the rail drew the 16x16 grid at 28px and it read as pixelated.
        const { container } = render(Sidebar, { mode: "buyer" });
        const mark = container.querySelector("img.mark") as HTMLImageElement;
        expect(mark.getAttribute("src")).toBe("/static/mark-large.svg");
        expect(mark.getAttribute("width")).toBe("32");
        expect(mark.getAttribute("height")).toBe("32");
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
        at("#/sites?mode=author");
        render(Sidebar, { mode: "author" });
        expect(screen.getByRole("link", { name: "Sites" })).toHaveAttribute(
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
        // Spelled out to "activity"/lens:"runs" rather than the "jobs"
        // alias (shell-4): a link identical to the hash already there does
        // not fire a hashchange, and a reader who had switched lens tabs
        // (which now write their own ?lens=) left a hash this action's old,
        // bare "?author=new" would not have differed from.
        expect(parseHash(action.getAttribute("href") ?? "")).toEqual({
            name: "activity",
            params: [],
            query: { mode: "author", author: "new", lens: "runs" },
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
        // B146: the form is a section now, never collapsed.
        expect(input.closest(".authoring")).not.toBeNull();
        expect(input.closest("details")).toBeNull();
        expect(parseHash(window.location.hash).query).toEqual({
            mode: "author",
            lens: "runs",
        });
        expect(fetchMock.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
    });

    it("still differs from a hash a lens tab switch already changed (shell-4)", () => {
        // The rail action's href must not equal a hash a reader could
        // already be on — a tab click that had rewritten ?lens= to
        // something other than "runs" used to leave the rail action a
        // no-op, because setting the hash to what it already was fires no
        // hashchange at all.
        window.history.replaceState(null, "", "#/activity?mode=author&lens=live");
        render(Sidebar, { mode: "author" });
        const href = screen.getByRole("link", { name: /Start a new pack/ }).getAttribute("href");
        expect(href).not.toBe(window.location.hash);
    });

    it("reopens the form on the same route without clearing a draft", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ items: [] }))));
        at("#/jobs?mode=author");
        render(Sidebar, { mode: "author" });
        render(Jobs);
        const input = screen.getByLabelText("What is the category?");
        const action = screen.getByRole("link", { name: /Start a new pack/ });
        at(action.getAttribute("href")!);
        await waitFor(() => expect(input).toHaveFocus());
        await fireEvent.input(input, { target: { value: "espresso machines" } });
        action.focus();
        at(action.getAttribute("href")!);
        await waitFor(() => expect(input).toHaveFocus());
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

describe("the rail folds (B167)", () => {
    const at = (hash: string) => {
        window.location.hash = hash;
    };

    it("has no Packs row: Packs is a section of Browse", () => {
        at("#/check?mode=author");
        render(Sidebar, { mode: "author" });
        expect(screen.queryByRole("link", { name: "Packs" })).toBeNull();
    });

    it("folds and unfolds Knowledge and System from their titles, and says so", async () => {
        at("#/check?mode=author");
        stubFetch({ "/api/settings": {} });
        render(Sidebar, { mode: "author" });
        for (const [title, row] of [
            ["Knowledge", "Overview"],
            ["System", "Activity"],
        ]) {
            const button = screen.getByRole("button", { name: title });
            expect(button).toHaveAttribute("aria-expanded", "true");
            expect(screen.getByRole("link", { name: row })).toBeInTheDocument();
            await fireEvent.click(button);
            expect(button).toHaveAttribute("aria-expanded", "false");
            expect(screen.queryByRole("link", { name: row })).toBeNull();
            await fireEvent.click(button);
            expect(button).toHaveAttribute("aria-expanded", "true");
            expect(screen.getByRole("link", { name: row })).toBeInTheDocument();
        }
    });

    it("leaves Check and This install as plain titles, not tabs", () => {
        at("#/check?mode=author");
        render(Sidebar, { mode: "author" });
        expect(screen.queryByRole("button", { name: "Check" })).toBeNull();
        expect(screen.queryByRole("button", { name: "This install" })).toBeNull();
    });

    it("remembers the fold in settings, and starts folded when it was left folded", async () => {
        at("#/check?mode=author");
        stubFetch({ "/api/settings": {} });
        const first = render(Sidebar, { mode: "author" });
        await fireEvent.click(screen.getByRole("button", { name: "System" }));
        const calls = vi.mocked(globalThis.fetch).mock.calls;
        await waitFor(() =>
            expect(
                calls.some(
                    ([url, init]) =>
                        String(url).includes("/api/settings") &&
                        (init as RequestInit)?.method === "POST" &&
                        String((init as RequestInit)?.body ?? "").includes("system"),
                ),
            ).toBe(true),
        );
        first.unmount();

        // A restart: the stored value comes back from the server.
        stubFetch({ "/api/settings": { rail_folded_groups: "system" } });
        render(Sidebar, { mode: "author" });
        await waitFor(() =>
            expect(screen.getByRole("button", { name: "System" })).toHaveAttribute(
                "aria-expanded",
                "false",
            ),
        );
        expect(screen.queryByRole("link", { name: "Activity" })).toBeNull();
        expect(screen.getByRole("link", { name: "Overview" })).toBeInTheDocument();
    });

    it("keeps the group holding the open screen open, whatever was stored", async () => {
        at("#/knowledge?mode=author");
        stubFetch({ "/api/settings": { rail_folded_groups: "knowledge,system" } });
        render(Sidebar, { mode: "author" });
        await waitFor(() =>
            expect(screen.getByRole("button", { name: "System" })).toHaveAttribute(
                "aria-expanded",
                "false",
            ),
        );
        expect(screen.getByRole("button", { name: "Knowledge" })).toHaveAttribute(
            "aria-expanded",
            "true",
        );
        expect(screen.getByRole("link", { name: "Browse" })).toHaveAttribute(
            "aria-current",
            "page",
        );
    });

    it("keeps the group of a retired address open too (#/packs renders Browse)", async () => {
        at("#/packs?mode=author");
        stubFetch({ "/api/settings": { rail_folded_groups: "knowledge" } });
        render(Sidebar, { mode: "author" });
        expect(screen.getByRole("button", { name: "Knowledge" })).toHaveAttribute(
            "aria-expanded",
            "true",
        );
    });
});
