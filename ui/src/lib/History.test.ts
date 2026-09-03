import { render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";
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
            },
            {
                lookup_id: "b2",
                created_at: "2026-09-02",
                source: "form",
                label: "Two",
                claim_count: 0,
            },
        ],
    },
};

describe("History", () => {
    beforeEach(() => {
        window.location.hash = "#/check?mode=author";
    });

    it("carries the mode into a stored result, instead of dropping the reader into buyer", async () => {
        stubFetch(ITEMS);
        render(History);
        const link = (await screen.findByRole("link", { name: "One" })) as HTMLAnchorElement;
        expect(link.getAttribute("href")).toContain("mode=author");
        expect(link.getAttribute("href")).toContain("result/a1");
    });

    it("says what the list is for when it is empty", async () => {
        stubFetch({ "/api/history": { items: [] } });
        render(History);
        expect(await screen.findByText(/Nothing asked yet/)).toBeInTheDocument();
    });

    it("as a page, offers comparing two of them", async () => {
        stubFetch(ITEMS);
        render(History, { page: true });
        const compare = (await screen.findByRole("link", {
            name: /Compare/,
        })) as HTMLAnchorElement;
        expect(compare.getAttribute("href")).toContain("compare");
    });
});
