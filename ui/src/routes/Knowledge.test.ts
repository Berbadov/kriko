import { fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Knowledge from "./Knowledge.svelte";
import { stubFetch } from "../lib/stub-fetch";

const STATUS = {
    enabled_packs: 1,
    counts: { packs: 1, subjects: 2, claims: 3, evidence: 4 },
};

const PACK = {
    pack_id: "org.kriko.cars",
    name: "Used cars",
    version: "1.0.0",
    enabled: true,
    subjects: 2,
    claims: 3,
    evidence: 4,
    digest: "abc123",
};

function serve(over: Record<string, unknown> = {}) {
    return stubFetch({
        "/api/status": STATUS,
        "/api/packs": [PACK],
        "/api/subjects": [],
        "/api/packs/org.kriko.cars/gaps": [],
        ...over,
    });
}

const SUBJECT = {
    subject_id: "s1",
    label: "Golf",
    kind: "thing",
    pack_id: "org.kriko.cars",
    claims: 2,
};

// What `/api/subjects/filters` returns (B180): every name, description and
// option below is the API's word, which is why the screen can show a filter
// it has never heard of.
const FILTERS = {
    filters: [
        {
            id: "pack",
            param: "pack_id",
            label: "Catalog",
            description: "Show products from one installed catalog.",
            options: [{ value: "org.kriko.cars", label: "Used cars", count: 2 }],
        },
        {
            id: "kind",
            param: "kind",
            label: "Kind",
            description: "The type of record a catalog holds.",
            options: [{ value: "thing", label: "Thing", count: 2 }],
        },
        {
            id: "evidence",
            param: "evidence",
            label: "Evidence",
            description: "How well the best risk is sourced.",
            options: [
                {
                    value: "none",
                    label: "No sources",
                    count: 1,
                    description: "No claim has a source.",
                },
            ],
        },
        {
            id: "severity",
            param: "severity",
            label: "Severity",
            description: "The most serious known risk.",
            options: [{ value: "high", label: "Serious", count: 1 }],
        },
    ],
};

describe("Knowledge", () => {
    beforeEach(() => vi.restoreAllMocks());

    it("shows counts before content, so arriving is orientation not a table dump", async () => {
        serve();
        render(Knowledge, {});
        await waitFor(() => expect(screen.getByText("subjects")).toBeInTheDocument());
        expect(screen.getByText("claims")).toBeInTheDocument();
    });

    it("shows three lenses, and no tab for what readers said (B166)", async () => {
        serve();
        render(Knowledge, {});
        await screen.findByRole("tab", { name: /What is here/ });
        expect(screen.getAllByRole("tab").map((tab) => tab.textContent?.trim())).toEqual([
            "What is here",
            "What is missing",
            "What is thin",
        ]);
        expect(screen.queryByText(/What readers said/)).toBeNull();
        expect(screen.queryByText(/Worth researching again/)).toBeNull();
    });

    it("opens on the lens the route named, and an old marks bookmark lands on the first", async () => {
        serve();
        const first = render(Knowledge, { lens: "gaps" });
        await waitFor(() =>
            expect(screen.getByRole("tab", { name: /What is missing/ })).toHaveAttribute(
                "aria-selected",
                "true",
            ),
        );
        first.unmount();
        // `#/marks` resolves to "all" in nav.ts, but a stale `lens=marked`
        // must not leave the screen with no tab selected either.
        render(Knowledge, { lens: "marked" });
        await waitFor(() =>
            expect(screen.getByRole("tab", { name: /What is here/ })).toHaveAttribute(
                "aria-selected",
                "true",
            ),
        );
    });

    it("never asks for the marks any more: the extension posts them, this screen does not read them", async () => {
        serve();
        render(Knowledge, {});
        await screen.findByRole("tab", { name: /What is here/ });
        const asked = vi.mocked(globalThis.fetch).mock.calls.map(([url]) => String(url));
        expect(asked.some((url) => url.startsWith("/api/marks"))).toBe(false);
    });

    it("moves the lens with arrow keys, the same roving-tabindex contract Activity's tabs carry (knowledge-28)", async () => {
        serve();
        render(Knowledge, {});
        const all = await screen.findByRole("tab", { name: /What is here/ });
        expect(all).toHaveAttribute("tabindex", "0");
        const gaps = screen.getByRole("tab", { name: /What is missing/ });
        expect(gaps).toHaveAttribute("tabindex", "-1");
        await fireEvent.keyDown(all, { key: "ArrowRight" });
        expect(gaps).toHaveAttribute("aria-selected", "true");
        expect(gaps).toHaveAttribute("tabindex", "0");
        expect(gaps).toHaveFocus();
        const thin = screen.getByRole("tab", { name: /What is thin/ });
        await fireEvent.keyDown(gaps, { key: "End" });
        expect(thin).toHaveAttribute("aria-selected", "true");
        expect(thin).toHaveFocus();
    });

    it("folds catalogs and drafts into one line that opens on press (B180)", async () => {
        serve();
        render(Knowledge, {});
        const line = await screen.findByRole("button", { name: /1 catalog/ });
        expect(line).toHaveAttribute("aria-expanded", "false");
        // Closed: the install form and the catalog cards are not on screen.
        expect(screen.queryByRole("heading", { name: /Catalogs/ })).toBeNull();
        await fireEvent.click(line);
        const heading = await screen.findByRole("heading", { name: /Catalogs/ });
        expect(line).toHaveAttribute("aria-expanded", "true");
        expect(await screen.findByText("Used cars")).toBeInTheDocument();
        expect(screen.getByRole("button", { name: "Install pack" })).toBeInTheDocument();
        // The panel opens under its own line, so it is the reader's choice
        // that moves the search down, never the arrival.
        expect(
            line.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING,
        ).toBeTruthy();
        await fireEvent.click(line);
        expect(screen.queryByRole("heading", { name: /Catalogs/ })).toBeNull();
    });

    it("counts switched-off catalogs and drafts on that one line", async () => {
        serve({
            "/api/packs": [PACK, { ...PACK, pack_id: "b", name: "Off one", enabled: false }],
            "/api/packs/b/gaps": [],
            ...drafted(),
        });
        render(Knowledge, {});
        const line = await screen.findByRole("button", {
            name: /2 catalogs, 1 off, 1 draft/,
        });
        await fireEvent.click(line);
        expect(await screen.findByText(/Off one is switched off/)).toBeInTheDocument();
    });

    it("opens the catalogs line when the address asks for it", async () => {
        window.location.hash = "#/knowledge?catalogs=1";
        serve();
        render(Knowledge, {});
        expect(await screen.findByRole("heading", { name: /Catalogs/ })).toBeInTheDocument();
        window.location.hash = "";
    });

    it("has no Updates block: no check button, no Update all, no index table", async () => {
        serve();
        render(Knowledge, {});
        await screen.findByRole("button", { name: /catalog/ });
        await openCatalogs();
        await screen.findByText("Used cars");
        expect(screen.queryByRole("button", { name: /Check for updates/ })).toBeNull();
        expect(screen.queryByRole("button", { name: /Update all/ })).toBeNull();
        expect(screen.queryByRole("heading", { name: /Updates/ })).toBeNull();
        const asked = vi.mocked(globalThis.fetch).mock.calls.map(([url]) => String(url));
        expect(asked.some((url) => url.startsWith("/api/packs/updates"))).toBe(false);
    });

    it("puts the search before any catalog card and the first result after it (B180)", async () => {
        serve({ "/api/subjects": [SUBJECT] });
        render(Knowledge, {});
        const search = await screen.findByLabelText("Search");
        const row = await screen.findByText("Golf");
        // Only the one-line summary sits above the search: no card, no form.
        expect(screen.queryByRole("button", { name: "Install pack" })).toBeNull();
        expect(document.querySelectorAll("article.card").length).toBe(0);
        expect(
            search.compareDocumentPosition(row) & Node.DOCUMENT_POSITION_FOLLOWING,
        ).toBeTruthy();
    });
});

describe("Browse filters (B180)", () => {
    beforeEach(() => {
        vi.restoreAllMocks();
        window.location.hash = "";
    });

    it("renders one control per filter row the API returns", async () => {
        serve({ "/api/subjects": [SUBJECT], "/api/subjects/filters": FILTERS });
        render(Knowledge, {});
        for (const name of ["Catalog", "Kind", "Evidence", "Severity"]) {
            expect(await screen.findByLabelText(name)).toBeInTheDocument();
        }
        expect(
            within(screen.getByLabelText("Evidence")).getByRole("option", {
                name: "No sources (1)",
            }),
        ).toBeInTheDocument();
    });

    it("shows a filter the screen has never heard of, because the row is all it needs", async () => {
        serve({
            "/api/subjects": [SUBJECT],
            "/api/subjects/filters": {
                filters: [
                    {
                        id: "zzz",
                        param: "zzz",
                        label: "Made up",
                        description: "d",
                        options: [{ value: "v", label: "Vee", count: 1 }],
                    },
                ],
            },
        });
        render(Knowledge, {});
        expect(await screen.findByLabelText("Made up")).toBeInTheDocument();
    });

    it("keeps each description closed until it is asked for", async () => {
        serve({ "/api/subjects": [SUBJECT], "/api/subjects/filters": FILTERS });
        render(Knowledge, {});
        const about = await screen.findByRole("button", { name: "About Evidence" });
        expect(about).toHaveAttribute("aria-expanded", "false");
        expect(screen.queryByText(/How well the best risk is sourced/)).toBeNull();
        await fireEvent.click(about);
        expect(about).toHaveAttribute("aria-expanded", "true");
        expect(screen.getByText(/How well the best risk is sourced/)).toBeInTheDocument();
        // Option descriptions come from the row too.
        expect(screen.getByText(/No claim has a source/)).toBeInTheDocument();
    });

    it("asks the list again with the chosen value, under the row's own parameter", async () => {
        serve({ "/api/subjects": [SUBJECT], "/api/subjects/filters": FILTERS });
        render(Knowledge, {});
        const select = await screen.findByLabelText("Severity");
        await fireEvent.change(select, { target: { value: "high" } });
        await waitFor(() => {
            const asked = vi.mocked(globalThis.fetch).mock.calls.map(([url]) => String(url));
            expect(
                asked.some((url) => url.startsWith("/api/subjects?") && url.includes("severity=high")),
            ).toBe(true);
        });
    });

    it("applies a filter named in the address, which is how Overview links in", async () => {
        window.location.hash = "#/knowledge?evidence=none";
        serve({ "/api/subjects": [SUBJECT], "/api/subjects/filters": FILTERS });
        render(Knowledge, {});
        await waitFor(() => {
            const asked = vi.mocked(globalThis.fetch).mock.calls.map(([url]) => String(url));
            expect(asked.some((url) => url.includes("evidence=none"))).toBe(true);
        });
        expect(await screen.findByLabelText("Evidence")).toHaveValue("none");
    });
});

// ── the card that would not go away ────────────────────────────────────
//
// "After making a pack, there's a warning banner with install it / forget. I
// click either one and the warning stays there." Both endpoints were correct.
// B129 had already made the card say "is installed" and left it a
// warning-coloured box in the alert position, which is the half anybody reads.
// Drafts sit inside the folded catalogs line since B180, so each test opens it.

const DRAFT = {
    slug: "widgets",
    root: "/root/.kriko/drafts/widgets",
    files: ["pack.toml"],
    artifact: null,
    pack_id: "widgets",
    name: "Widgets",
    version: "0.1.0",
    error: "",
    installed_as: "",
};

const drafted = (over = {}) => ({
    "/api/packs/drafts": { items: [{ ...DRAFT, ...over }] },
});

async function openCatalogs() {
    await fireEvent.click(await screen.findByRole("button", { name: /catalog/ }));
}

describe("a drafted pack", () => {
    beforeEach(() => vi.restoreAllMocks());

    it("is an alert while it is still waiting on the reader", async () => {
        serve(drafted());
        render(Knowledge);
        await openCatalogs();
        const card = await screen.findByText(/is a draft/);
        expect(card.closest("article")?.className).toContain("notice");
    });

    it("stops being an alert once it is in the store", async () => {
        serve(drafted({ installed_as: "widgets" }));
        render(Knowledge);
        await openCatalogs();
        const card = await screen.findByText(/is installed/);
        expect(card.closest("article")?.className).not.toContain("notice");
    });

    it("offers hiding only once there is nothing left to decide", async () => {
        serve(drafted());
        render(Knowledge);
        await openCatalogs();
        await screen.findByText(/is a draft/);
        expect(screen.queryByRole("button", { name: "Hide" })).toBeNull();
    });

    it("can be hidden without throwing away what the agent wrote", async () => {
        serve(drafted({ installed_as: "widgets" }));
        render(Knowledge);
        await openCatalogs();
        (await screen.findByRole("button", { name: "Hide" })).click();

        await waitFor(() => expect(screen.queryByText(/is installed/)).toBeNull());
        const calls = vi.mocked(globalThis.fetch).mock.calls;
        // Written down, or it comes back on reload, which is the same
        // complaint the reader already made.
        await waitFor(() =>
            expect(
                calls.some(
                    ([url, init]) =>
                        String(url).includes("/api/settings") &&
                        String((init as RequestInit)?.body ?? "").includes("widgets"),
                ),
            ).toBe(true),
        );
        // And nothing was deleted: hiding a receipt must not destroy the one
        // copy of what the agent proposed.
        expect(
            calls.some(
                ([url, init]) =>
                    String(url).includes("/api/packs/drafts/widgets") &&
                    (init as RequestInit)?.method === "DELETE",
            ),
        ).toBe(false);
    });

    it("stays hidden when the screen is loaded again", async () => {
        serve({
            ...drafted({ installed_as: "widgets" }),
            "/api/settings": { knowledge_hidden_drafts: "widgets" },
        });
        render(Knowledge);
        await waitFor(() => expect(screen.queryByText(/is installed/)).toBeNull());
    });
});
