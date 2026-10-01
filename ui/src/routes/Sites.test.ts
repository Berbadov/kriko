import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import { stubFetch } from "../lib/stub-fetch";
import Sites from "./Sites.svelte";

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

const DETAIL = {
    site: "learned.test",
    id: "local.learned.test",
    pack_id: "",
    source: "local",
    editable: true,
    match: ["*://*.learned.test/*"],
    subject_kind: "product",
    rules: [
        { key: "brand", kind: "identity", labels: ["Marka"], from: "" },
        { key: "price", kind: "context", labels: ["Fiyat"], from: "" },
    ],
    labels: ["marka", "fiyat"],
    unmapped: [
        { label: "Renk", seen: 4, last_at: "2026-09-29T09:00:00Z",
          sample_url: "https://learned.test/item/9" },
    ],
    sample_url: "https://learned.test/item/1",
    spec: {
        id: "local.learned.test",
        site: "learned.test",
        identity: { brand: { labels: ["Marka"] } },
    },
};

describe("Sites", () => {
    it("lists every readable site, even when several packs ship the same one", async () => {
        stubFetch({ "/api/sites": ROWS });
        render(Sites);
        const list = await screen.findByRole("list", { name: "Readable sites" });
        expect(list.querySelectorAll("li.krow")).toHaveLength(ROWS.registered.length);
        const rows = [...list.querySelectorAll("li.krow")].map((row) => row.textContent ?? "");
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

    it("expands a site into its rules, unmapped labels and sample page (B181)", async () => {
        stubFetch({
            "/api/sites": ROWS,
            "/api/sites/learned.test/detail": DETAIL,
        });
        render(Sites);
        const buttons = await screen.findAllByText("Detail");
        await fireEvent.click(buttons[ROWS.registered.length - 1]);
        expect(await screen.findByText(/Fields read/)).toBeInTheDocument();
        expect(screen.getByText(/Marka/)).toBeInTheDocument();
        expect(screen.getByText(/Renk/)).toBeInTheDocument();
        expect(screen.getByText(/Last page asked about/)).toBeInTheDocument();
    });

    it("offers an amendment only on a learned site, and saves it (B181)", async () => {
        stubFetch({
            "/api/sites": ROWS,
            "/api/sites/learned.test/detail": DETAIL,
            "put:/api/sites/learned.test": { host: "learned.test" },
        });
        render(Sites);
        const buttons = await screen.findAllByText("Detail");
        await fireEvent.click(buttons[ROWS.registered.length - 1]);
        expect(await screen.findByText(/Amend the rules/)).toBeInTheDocument();
        const save = screen.getAllByRole("button", { name: "Save" })[0];
        await fireEvent.click(save);
        expect(await screen.findByText(/Saved/)).toBeInTheDocument();
    });

    it("marks a pack's site read-only (B181)", async () => {
        stubFetch({
            "/api/sites": ROWS,
            "/api/sites/example.test/detail": { ...DETAIL, editable: false,
                pack_id: "pack.one", source: "pack", spec: null, site: "example.test" },
        });
        render(Sites);
        const buttons = await screen.findAllByText("Detail");
        await fireEvent.click(buttons[0]);
        expect(await screen.findByText(/read-only here/)).toBeInTheDocument();
        expect(screen.queryByText(/Amend the rules/)).toBeNull();
    });
});
