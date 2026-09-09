import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Report from "./Report.svelte";
import { stubFetch } from "./stub-fetch";
import type { LookupResult } from "./types";

const RESULT: LookupResult = {
    method: "exact",
    coverage: "RISKS_FOUND",
    claims: [
        {
            claim_id: "c1",
            title: "Spindle runout",
            body: "Wears with duty cycles.",
            advice: "Ask for the service record.",
            severity: "high",
            domain: "mech",
            subject: "Bench Grinder 8in",
            pack_id: "tools",
            relevance: 0.2712,
            why: ["high severity", "best source is specialist (trust 0.80)"],
            sources: [
                { domain: "forum.test", quote: "mine went at 300h", tier: "forum_ugc", stance: "supports" },
            ],
        },
    ],
};

const ok = (body: unknown) => new Response(JSON.stringify(body));

describe("Report — one payload, two renderings", () => {
    it("gives a buyer urgency and what to ask, not the score", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => ok({ checked: [] })));
        render(Report, { props: { result: RESULT, mode: "buyer" } });
        // Twice by design: the section heading carries the worst severity in
        // it as a tile, and the card carries its own.
        expect(await screen.findAllByText("Serious")).not.toHaveLength(0);
        expect(await screen.findByText(/Ask for the service record/)).toBeInTheDocument();
        // The count appears twice by design: on the claim's meta line and on
        // the collapsed sources summary.
        expect(await screen.findAllByText(/1 source reports this/)).not.toHaveLength(0);
        expect(screen.queryByText(/relevance/)).not.toBeInTheDocument();
        expect(screen.queryByText(/forum_ugc/)).not.toBeInTheDocument();
    });

    it("gives an author the score, the pack and the reasons", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => ok({ checked: [] })));
        render(Report, { props: { result: RESULT, mode: "author" } });
        expect(await screen.findByText(/relevance 0.2712/)).toBeInTheDocument();
        expect(await screen.findByText(/best source is specialist/)).toBeInTheDocument();
    });

    it("groups under the pack's own domain and counts the serious ones", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => ok({ checked: [] })));
        render(Report, { props: { result: RESULT } });
        // By pattern: the heading now carries its worst severity and a count
        // alongside the domain name.
        expect(
            await screen.findByRole("heading", { name: /mech/ }),
        ).toBeInTheDocument();
        expect(await screen.findByText(/1 serious/)).toBeInTheDocument();
    });

    it("persists a handled risk against the stored lookup", async () => {
        const fetcher = vi.fn(async (path: string, init?: RequestInit) =>
            init?.method === "POST" ? ok({ checked: ["c1"] }) : ok({ checked: [] }),
        );
        vi.stubGlobal("fetch", fetcher);
        render(Report, { props: { result: RESULT, lookupId: "abc" } });
        await fireEvent.click(await screen.findByLabelText("Handled"));
        expect(await screen.findByText(/1 handled/)).toBeInTheDocument();
        const [path, init] = fetcher.mock.calls.at(-1)!;
        expect(path).toBe("/api/lookups/abc/checked");
        expect(JSON.parse(String(init!.body))).toEqual({
            claim_key: "c1",
            checked: true,
        });
    });

    it("says why an empty report is empty, and which kind of empty it is", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => ok({ checked: [] })));
        const { unmount } = render(Report, {
            props: { result: { method: "no_match", coverage: "NOT_MATCHED", claims: [] } },
        });
        expect(await screen.findByText(/No installed pack recognised/)).toBeInTheDocument();
        unmount();
        render(Report, {
            props: { result: { method: "exact", coverage: "NO_RISKS", claims: [] } },
        });
        expect(await screen.findByText(/coverage gap, not a clean bill/)).toBeInTheDocument();
    });

    it("leads with a verdict, not with a bare count", async () => {
        stubFetch({ "/api/lookups/L1/checked": { checked: [] } });
        render(Report, { result: RESULT, lookupId: "L1" });
        expect(await screen.findByText(/serious/)).toBeInTheDocument();
        expect(screen.getByRole("img", { name: /severity mix/i })).toBeInTheDocument();
    });

    it("shows the reader how the match was made beside the verdict", () => {
        stubFetch({ "/api/lookups/L1/checked": { checked: [] } });
        render(Report, { result: RESULT, lookupId: "L1" });
        expect(screen.getByText(/Matched/)).toBeInTheDocument();
    });

    it("offers a printable copy of the answer", async () => {
        stubFetch({ "/api/lookups/L1/checked": { checked: [] } });
        render(Report, { result: RESULT, lookupId: "L1" });
        expect(screen.getByRole("button", { name: /Print/ })).toBeInTheDocument();
    });

    it("reads both halves of triage in one request", async () => {
        // Two requests for one screen paints the checkboxes and then, a beat
        // later, the notes — which reads as two pages loading.
        const fetcher = vi.fn(async (_path: string) =>
            ok({ checked: ["c1"], notes: { c1: "said done" } }),
        );
        vi.stubGlobal("fetch", fetcher);
        render(Report, { props: { result: RESULT, lookupId: "L1" } });
        expect(await screen.findByDisplayValue("said done")).toBeInTheDocument();
        // Triage specifically: the report also reads the stored fact-check
        // verdicts, and that is one request for the whole screen too.
        expect(
            fetcher.mock.calls.map((c) => String(c[0])).filter((p) => p.includes("triage")),
        ).toEqual(["/api/lookups/L1/triage"]);
    });

    it("persists what the seller said against the claim", async () => {
        const fetcher = vi.fn(async (path: string, init?: RequestInit) =>
            init?.method === "POST"
                ? ok({ notes: { c1: "belt done at 140k" } })
                : ok({ checked: [], notes: {} }),
        );
        vi.stubGlobal("fetch", fetcher);
        render(Report, { props: { result: RESULT, lookupId: "L1" } });
        await fireEvent.click(await screen.findByText(/Add what the seller said/));
        const box = await screen.findByPlaceholderText(/receipt promised/);
        // Input then blur: the field is `bind:value`, so setting the DOM value
        // on the blur event alone never reaches the component's own state.
        await fireEvent.input(box, { target: { value: "belt done at 140k" } });
        await fireEvent.blur(box);
        const [path, init] = fetcher.mock.calls.at(-1)!;
        expect(path).toBe("/api/lookups/L1/notes");
        expect(JSON.parse(String(init!.body))).toEqual({
            claim_key: "c1",
            note: "belt done at 140k",
        });
    });

    it("shows progress once something is ticked, and not before", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => ok({ checked: [], notes: {} })));
        const { unmount } = render(Report, { props: { result: RESULT, lookupId: "L1" } });
        expect(screen.queryByText(/dealt with/)).not.toBeInTheDocument();
        unmount();
        vi.stubGlobal("fetch", vi.fn(async () => ok({ checked: ["c1"], notes: {} })));
        render(Report, { props: { result: RESULT, lookupId: "L1" } });
        expect(await screen.findByText(/All 1 dealt with/)).toBeInTheDocument();
    });

    it("hands the whole answer over as text, notes included", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => ok({ checked: [], notes: { c1: "said done" } })));
        const writeText = vi.fn(async (_text: string) => {});
        vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
        render(Report, { props: { result: RESULT, lookupId: "L1" } });
        await screen.findByDisplayValue("said done");
        await fireEvent.click(screen.getByRole("button", { name: /Copy for a mechanic/ }));
        expect(await screen.findByText(/Copied as Markdown/)).toBeInTheDocument();
        expect(writeText.mock.calls[0][0]).toContain("**Answer:** said done");
    });

    it("falls back to selectable text when the webview refuses the clipboard", async () => {
        // The bug this whole line of work started from is a button that
        // silently does nothing.
        vi.stubGlobal("fetch", vi.fn(async () => ok({ checked: [], notes: {} })));
        vi.stubGlobal("navigator", {
            ...navigator,
            clipboard: {
                writeText: async () => {
                    throw new Error("denied");
                },
            },
        });
        render(Report, { props: { result: RESULT, lookupId: "L1" } });
        await fireEvent.click(
            await screen.findByRole("button", { name: /Copy for a mechanic/ }),
        );
        expect(await screen.findByText(/would not take it to the clipboard/)).toBeInTheDocument();
    });

    it("says what the answer was computed against", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => ok({ checked: [], notes: {} })));
        render(Report, {
            props: {
                result: { ...RESULT, context: { duty_hours: 300 }, context_units: { duty_hours: "h" } },
                lookupId: "L1",
            },
        });
        expect(await screen.findByText(/300 h/)).toBeInTheDocument();
    });

    it("answers the inverse question a short report raises", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => ok({ checked: [], notes: {} })));
        render(Report, { props: { result: RESULT } });
        expect(await screen.findByText(/Why might this be short/)).toBeInTheDocument();
        expect(screen.getByText(/not a risk that has been ruled out/)).toBeInTheDocument();
    });

    it("puts a dispute where the reader will see it, not behind two folds", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => ok({ checked: [], notes: {} })));
        render(Report, {
            props: {
                result: { ...RESULT, claims: [{ ...RESULT.claims[0], disputed: true }] },
                mode: "buyer",
            },
        });
        const badge = await screen.findByText("disputed");
        expect(badge.closest("details")).toBeNull();
    });

    it("links to the sheet the reader takes to the seller", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => ok({ checked: [], notes: {} })));
        render(Report, { props: { result: RESULT, lookupId: "L1" } });
        const link = await screen.findByRole("link", { name: "Question sheet" });
        expect(link.getAttribute("href")).toContain("questions");
        expect(link.getAttribute("href")).toContain("id=L1");
    });
});

describe("Report — what the cited pages say now", () => {
    const CITED: LookupResult = {
        ...RESULT,
        claims: [
            {
                ...RESULT.claims[0],
                sources: [
                    {
                        url: "https://forum.test/a",
                        domain: "forum.test",
                        quote: "mine went at 300h",
                        tier: "forum_ugc",
                        stance: "supports",
                    },
                ],
            },
            {
                ...RESULT.claims[0],
                claim_id: "c2",
                title: "Brush wear",
                sources: [
                    {
                        url: "https://forum.test/b",
                        domain: "forum.test",
                        quote: "brushes at 200h",
                        tier: "forum_ugc",
                        stance: "supports",
                    },
                ],
            },
        ],
    };

    const check = (over: Record<string, unknown>) => ({
        pack_id: "tools",
        claim_id: "c1",
        verdict: "quoted",
        detail: "",
        sources: [],
        subject_id: "s",
        title: "Spindle runout",
        checked_at: "2026-09-08T09:00:00+00:00",
        ...over,
    });

    it("reads every stored verdict in one request, not one per card", async () => {
        // Forty claims is forty requests to be told "not checked yet".
        const fetch = vi.fn(async (path: string) =>
            ok(
                String(path).startsWith("/api/factcheck")
                    ? { items: [check({})], counts: { quoted: 1 } }
                    : { checked: [] },
            ),
        );
        vi.stubGlobal("fetch", fetch);
        render(Report, { props: { result: CITED, mode: "buyer" } });
        expect(await screen.findByText("Source still says this")).toBeInTheDocument();
        const calls = fetch.mock.calls.filter((c) =>
            String(c[0]).startsWith("/api/factcheck"),
        );
        expect(calls).toHaveLength(1);
    });

    it("sweeps the sources one at a time rather than all at once", async () => {
        /* Forty parallel fetches at forty domains, from the reader's own
         * address, is a burst that looks like a scraper to every one of them.
         * The app has no business doing that on their behalf, so the button
         * walks the list. */
        let inFlight = 0;
        let peak = 0;
        const fetch = vi.fn(async (path: string, init?: RequestInit) => {
            if (String(path).startsWith("/api/factcheck") && init?.method === "POST") {
                inFlight += 1;
                peak = Math.max(peak, inFlight);
                await new Promise((resolve) => setTimeout(resolve, 5));
                inFlight -= 1;
                return ok(check({ claim_id: "c1" }));
            }
            return ok(
                String(path).startsWith("/api/factcheck")
                    ? { items: [], counts: {} }
                    : { checked: [] },
            );
        });
        vi.stubGlobal("fetch", fetch);
        render(Report, { props: { result: CITED, mode: "buyer" } });
        await fireEvent.click(
            await screen.findByRole("button", { name: "Check every source" }),
        );
        await vi.waitFor(() =>
            expect(
                fetch.mock.calls.filter((c) => (c[1] as RequestInit)?.method === "POST"),
            ).toHaveLength(2),
        );
        expect(peak).toBe(1);
    });

    it("stays quiet when the verdicts cannot be read", async () => {
        // A supplementary badge on a report that is complete without it. A
        // banner over someone's answer because a status table would not read
        // is the tail wagging the dog.
        const fetch = vi.fn(async (path: string) =>
            String(path).startsWith("/api/factcheck")
                ? new Response("boom", { status: 500 })
                : ok({ checked: [] }),
        );
        vi.stubGlobal("fetch", fetch);
        render(Report, { props: { result: CITED, mode: "buyer" } });
        expect(await screen.findByText("Spindle runout")).toBeInTheDocument();
        expect(screen.queryByText(/boom|500/)).toBeNull();
    });

    it("offers no sweep at all when nothing carries a link", async () => {
        vi.stubGlobal("fetch", vi.fn(async () => ok({ checked: [] })));
        render(Report, { props: { result: RESULT, mode: "buyer" } });
        expect(await screen.findByText("Spindle runout")).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: /Check every source/ })).toBeNull();
    });
});
