import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import History from "./History.svelte";
import { stubFetch } from "./stub-fetch";

const ITEMS = {
    "/api/history": {
        items: [
            {
                lookup_id: "a1",
                created_at: "2026-09-01",
                source: "url",
                label: "One",
                claim_count: 3,
                category: "Alpha",
                packs: [{ pack_id: "p", name: "Alpha" }],
            },
            {
                lookup_id: "b2",
                created_at: "2026-09-02",
                source: "form",
                label: "Two",
                claim_count: 0,
                category: "",
                packs: [],
            },
        ],
    },
};

const row = (id: string, label: string, category: string) => ({
    lookup_id: id,
    created_at: "2026-09-03",
    source: "url",
    label,
    claim_count: 1,
    category,
    packs: category ? [{ pack_id: "p", name: category }] : [],
});

describe("History", () => {
    beforeEach(() => {
        window.location.hash = "#/history";
        vi.restoreAllMocks();
    });

    it("links a stored result with no mode on the address (B165)", async () => {
        stubFetch(ITEMS);
        render(History);
        const link = (await screen.findByRole("link", { name: "One" })) as HTMLAnchorElement;
        expect(link.getAttribute("href")).not.toContain("mode=");
        expect(link.getAttribute("href")).toContain("result/a1");
    });

    it("says what the list is for when it is empty, and points at the extension (B163)", async () => {
        stubFetch({ "/api/history": { items: [] } });
        render(History);
        expect(await screen.findByText(/Nothing asked yet/)).toBeInTheDocument();
        const action = screen.getByRole("link", { name: "Browser extension" });
        expect(action.getAttribute("href")).toBe("#/extension");
        expect(screen.queryByRole("link", { name: "Run a check" })).toBeNull();
    });

    it("as a page, offers comparing two of them", async () => {
        stubFetch(ITEMS);
        render(History, { page: true });
        const compare = (await screen.findByRole("link", {
            name: /Compare/,
        })) as HTMLAnchorElement;
        expect(compare.getAttribute("href")).toContain("compare");
    });

    it("as a page, groups checks under the category the API row names, with counts (B182)", async () => {
        stubFetch({
            "/api/history": {
                items: [
                    row("1", "Golf", "Alpha"),
                    row("2", "Polo", "Alpha"),
                    row("3", "Drill", "Beta"),
                ],
            },
        });
        render(History, { page: true });
        const alpha = await screen.findByRole("region", { name: "Alpha" });
        expect(within(alpha).getByText("2 checks")).toBeInTheDocument();
        expect(within(alpha).getByRole("link", { name: "Golf" })).toBeInTheDocument();
        expect(within(alpha).queryByRole("link", { name: "Drill" })).toBeNull();
        const beta = screen.getByRole("region", { name: "Beta" });
        expect(within(beta).getByText("1 check")).toBeInTheDocument();
    });

    it("names the group of checks no pack answered, and puts it last", async () => {
        stubFetch(ITEMS);
        render(History, { page: true });
        await screen.findByRole("region", { name: "Alpha" });
        const names = screen.getAllByRole("region").map((r) => r.getAttribute("aria-label"));
        expect(names).toEqual(["Alpha", "No catalog"]);
    });

    it("folds repeat checks of one product into one card that opens the newest (B182)", async () => {
        stubFetch({
            "/api/history": {
                items: [
                    row("new", "MacBook Air", "Alpha"),
                    row("mid", "MacBook Air", "Alpha"),
                    row("old", "MacBook Air", "Alpha"),
                ],
            },
        });
        render(History, { page: true });
        const links = await screen.findAllByRole("link", { name: "MacBook Air" });
        expect(links).toHaveLength(1);
        expect(links[0].getAttribute("href")).toContain("result/new");
        expect(screen.getByText("3 checks", { selector: ".badge" })).toBeInTheDocument();
    });

    it("forgetting a folded card forgets every check behind it", async () => {
        stubFetch({
            "/api/history": {
                items: [row("new", "MacBook Air", "Alpha"), row("old", "MacBook Air", "Alpha")],
            },
            "/api/history/": { deleted: true },
        });
        render(History, { page: true });
        await fireEvent.click(await screen.findByRole("button", { name: "Forget" }));
        await waitFor(() => {
            const deleted = vi
                .mocked(globalThis.fetch)
                .mock.calls.filter(([, init]) => (init as RequestInit)?.method === "DELETE")
                .map(([url]) => String(url));
            expect(deleted.sort()).toEqual(["/api/history/new", "/api/history/old"]);
        });
    });

    it("in the rail, folds repeats too and shows no group heading", async () => {
        stubFetch({
            "/api/history": {
                items: [row("new", "Same", "Alpha"), row("old", "Same", "Alpha")],
            },
        });
        render(History);
        expect(await screen.findAllByRole("link", { name: "Same" })).toHaveLength(1);
        expect(screen.queryByRole("region")).toBeNull();
    });
});
