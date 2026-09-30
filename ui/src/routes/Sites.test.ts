import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import { stubFetch } from "../lib/stub-fetch";
import Sites from "./Sites.svelte";

// B156: the installed build sat on "Reading the adapters" for good. /api/sites
// had answered in 30 ms; the screen then threw `each_key_duplicate`, because
// several packs each ship an adapter for the same site and the row key was
// `site + source`. This is the real shape of that answer: one site, one
// source, three different packs.
const shared = (pack_id: string) => ({
    site: "example.test",
    id: "example",
    pack_id,
    match: ["*://*.example.test/item/*"],
    source: "pack",
    activation: { host: "example.test", state: "active", detail: "" },
});

const ROWS = {
    registered: [
        shared("pack.one"),
        shared("pack.two"),
        shared("pack.three"),
        {
            site: "other.test",
            id: "other",
            pack_id: "pack.one",
            match: [],
            source: "pack",
            activation: { host: "other.test", state: "active", detail: "" },
        },
        {
            site: "learned.test",
            id: "learned",
            pack_id: "",
            match: [],
            source: "local",
            activation: { host: "learned.test", state: "active", detail: "" },
        },
    ],
    requested: [
        {
            host: "asked.test",
            asks: 2,
            sample_url: "https://asked.test/item/1",
            title: "",
            state: "open",
            detail: "",
            first_at: "2026-09-29T09:00:00Z",
            last_at: "2026-09-29T09:05:00Z",
        },
    ],
};

describe("Sites", () => {
    it("lists every readable site, even when several packs ship the same one", async () => {
        stubFetch({ "/api/sites": ROWS });
        render(Sites);

        const list = await screen.findByRole("list", { name: "Readable sites" });
        // Three packs, one site: three rows, none of them collapsed or lost.
        expect(list.querySelectorAll("li")).toHaveLength(ROWS.registered.length);
        const rows = [...list.querySelectorAll("li")].map((row) => row.textContent ?? "");
        for (const pack of ["pack.one", "pack.two", "pack.three"]) {
            expect(
                rows.some((row) => row.includes("example.test") && row.includes(`from ${pack}`)),
            ).toBe(true);
        }
        expect(rows.some((row) => row.includes("other.test"))).toBe(true);
        expect(rows.some((row) => row.includes("learned.test") && row.includes("learned here"))).toBe(true);
    });

    it("leaves the loading sentence and lists what was asked for", async () => {
        stubFetch({ "/api/sites": ROWS });
        render(Sites);

        expect(await screen.findByText("asked.test")).toBeInTheDocument();
        expect(screen.queryByText(/Reading the adapters/)).toBeNull();
    });
});
