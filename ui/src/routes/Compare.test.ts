import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { stubFetch } from "../lib/stub-fetch";
import Compare from "./Compare.svelte";

const HISTORY = {
    "/api/history": {
        items: [
            { lookup_id: "a1", created_at: "2026-09-01", source: "url", label: "One", claim_count: 2 },
            { lookup_id: "b2", created_at: "2026-09-02", source: "url", label: "Two", claim_count: 1 },
        ],
    },
};

const claim = (id: string, severity: string) => ({
    claim_id: id, title: `T-${id}`, body: "b", severity,
    subject: "s", relevance: 0.5, pack_id: "p",
});

const BOTH = {
    ...HISTORY,
    "/api/lookup/a1": {
        lookup_id: "a1", created_at: "", source: "url", label: "One", request: {},
        response: { method: "exact", claims: [claim("x", "high"), claim("y", "low")] },
    },
    "/api/lookup/b2": {
        lookup_id: "b2", created_at: "", source: "url", label: "Two", request: {},
        response: { method: "exact", claims: [claim("x", "high")] },
    },
};

describe("Compare", () => {
    beforeEach(() => {
        window.location.hash = "#/compare?left=a1&right=b2";
    });

    it("puts the two labels at the head of their columns", async () => {
        // By role, not by text: each label also appears as an <option> in the
        // pickers, so a bare findByText("One") matches two elements and says
        // nothing about which column the reader is reading.
        stubFetch(BOTH);
        render(Compare);
        expect(
            await screen.findByRole("columnheader", { name: "One" }),
        ).toBeInTheDocument();
        expect(screen.getByRole("columnheader", { name: "Two" })).toBeInTheDocument();
    });

    it("says how the two differ before listing how", async () => {
        stubFetch(BOTH);
        render(Compare);
        expect(await screen.findByText(/1 in both/)).toBeInTheDocument();
        expect(screen.getByText(/1 only in One/)).toBeInTheDocument();
    });

    it("asks for two answers when the link names none", async () => {
        window.location.hash = "#/compare";
        stubFetch(HISTORY);
        render(Compare);
        expect(await screen.findByLabelText("First")).toBeInTheDocument();
        expect(screen.getByLabelText("Second")).toBeInTheDocument();
    });

    it("lines up three, which is what a shortlist actually looks like", async () => {
        const third = {
            lookup_id: "c3", created_at: "2026-09-03", source: "url",
            label: "Three", claim_count: 1,
        };
        window.location.hash = "#/compare?ids=a1,b2,c3";
        stubFetch({
            ...BOTH,
            "/api/history": { items: [...HISTORY["/api/history"].items, third] },
            "/api/lookup/c3": {
                lookup_id: "c3", created_at: "", source: "url", label: "Three", request: {},
                response: { method: "exact", claims: [claim("z", "high")] },
            },
        });
        render(Compare);
        expect(
            await screen.findByRole("columnheader", { name: "Three" }),
        ).toBeInTheDocument();
        expect(screen.getByText(/0 in all 3/)).toBeInTheDocument();
        // Every row is three wide, and a risk only the third one has reads as
        // present there and absent — a dash, not a blank — in the other two.
        const zRow = screen.getByRole("rowheader", { name: "T-z" }).closest("tr")!;
        expect(zRow.querySelectorAll("td")).toHaveLength(3);
        expect(zRow.textContent).toBe("T-zNoneNoneSerious");
    });

    it("still honours the report's own two-sided link", async () => {
        // Every stored report links here with ?left=; a link is forever.
        window.location.hash = "#/compare?left=a1&right=b2";
        stubFetch(BOTH);
        render(Compare);
        expect(
            await screen.findByRole("columnheader", { name: "One" }),
        ).toBeInTheDocument();
    });

    it("accepts an id as a path segment, which is all the extension can send", async () => {
        // `/api/focus` refuses a query string on purpose — a route posted by a
        // web page is only safe to act on because its shape is closed. So the
        // panel's "Compare" button can only say `compare/<id>`, and this is
        // the same destination in that alphabet: one column seeded, the rest
        // left to pick, which is what "compare this with something" means.
        window.location.hash = "#/compare/a1";
        stubFetch(BOTH);
        render(Compare);
        const first = (await screen.findByLabelText("First")) as HTMLSelectElement;
        expect(first.value).toBe("a1");
        // And no table yet: one answer is not a comparison, so the screen is
        // waiting on the reader for the other side rather than pretending.
        expect(screen.queryByRole("columnheader", { name: "One" })).toBeNull();
    });

    it("says there is nothing to compare with fewer than two stored answers", async () => {
        window.location.hash = "#/compare";
        stubFetch({ "/api/history": { items: [HISTORY["/api/history"].items[0]] } });
        render(Compare);
        expect(await screen.findByText(/two saved checks/i)).toBeInTheDocument();
    });
});

const SUBJECT = (id: string, rows: [string, string, string][]) => ({
    subject_id: id, pack_id: "p", kind: "k", label: id, relations: [], claims: [],
    attributes: [
        { key: "id_key", value_text: "x", unit: "", is_identity: 1, label: "Identity" },
        ...rows.map(([label, value, source]) => ({
            key: label.toLowerCase(), value_text: value, unit: "", is_identity: 0,
            label, source_url: source,
        })),
    ],
});

const WITH_SPECS = {
    ...BOTH,
    "/api/lookup/a1": {
        ...BOTH["/api/lookup/a1"],
        response: { ...BOTH["/api/lookup/a1"].response, subjects: ["sa"] },
    },
    "/api/lookup/b2": {
        ...BOTH["/api/lookup/b2"],
        response: { ...BOTH["/api/lookup/b2"].response, subjects: ["sb"] },
    },
    "/api/subjects/sa": SUBJECT("sa", [
        ["Chipset", "A16", "https://e.org/a"], ["Weight", "171 g", ""],
    ]),
    "/api/subjects/sb": SUBJECT("sb", [["Chipset", "A17", "https://e.org/b"]]),
};

describe("Compare specifications (B173)", () => {
    beforeEach(() => {
        window.location.hash = "#/compare?left=a1&right=b2";
    });

    it("lines the specifications up row by row, named by the pack", async () => {
        stubFetch(WITH_SPECS);
        render(Compare);
        const chipset = (await screen.findByRole("rowheader", { name: "Chipset" })).closest("tr")!;
        expect(chipset.textContent).toBe("ChipsetA16A17");
        const weight = screen.getByRole("rowheader", { name: "Weight" }).closest("tr")!;
        expect(weight.textContent).toBe("Weight171 gNot recorded");
        // Identity keys make the product; they are not specifications.
        expect(screen.queryByRole("rowheader", { name: "Identity" })).toBeNull();
    });

    it("shows where each figure came from only when asked, one row at a time", async () => {
        stubFetch(WITH_SPECS);
        render(Compare);
        const chipset = await screen.findByRole("button", { name: "Chipset" });
        expect(screen.queryByRole("link", { name: "Source" })).toBeNull();
        await fireEvent.click(chipset);
        expect(screen.getAllByRole("link", { name: "Source" })).toHaveLength(2);
        await fireEvent.click(screen.getByRole("button", { name: "Weight" }));
        // Weight has one sourced cell at most (none), and Chipset's closed.
        expect(screen.queryAllByRole("link", { name: "Source" })).toHaveLength(0);
        expect(screen.getAllByText("No source").length).toBeGreaterThan(0);
    });

    it("opens one section at a time, specifications first when there are some", async () => {
        stubFetch(WITH_SPECS);
        render(Compare);
        await screen.findByRole("rowheader", { name: "Chipset" });
        expect(screen.queryByRole("rowheader", { name: "T-x" })).toBeNull();
        await fireEvent.click(screen.getByRole("button", { name: /Known risks/ }));
        expect(screen.getByRole("rowheader", { name: "T-x" })).toBeInTheDocument();
        expect(screen.queryByRole("rowheader", { name: "Chipset" })).toBeNull();
    });

    it("opens a risk's detail on demand", async () => {
        stubFetch(BOTH);
        render(Compare);
        await fireEvent.click(await screen.findByRole("button", { name: "T-x" }));
        expect(screen.getAllByText("b").length).toBeGreaterThan(0);
    });
});

const DRAFT = {
    draft_id: "d1", name: "Shortlist", lookup_ids: ["a1", "b2"],
    created_at: "", updated_at: "",
};

describe("Compare drafts (B183)", () => {
    beforeEach(() => {
        window.location.hash = "#/compare";
    });

    it("lists saved drafts and opens one into the pickers", async () => {
        stubFetch({ ...BOTH, "/api/compare-drafts": { items: [DRAFT], max: 4 } });
        render(Compare);
        await fireEvent.click(await screen.findByRole("button", { name: "Shortlist" }));
        await waitFor(() =>
            expect((screen.getByLabelText("First") as HTMLSelectElement).value).toBe("a1"),
        );
        expect((screen.getByLabelText("Draft name") as HTMLInputElement).value).toBe(
            "Shortlist",
        );
        expect(window.location.hash).toContain("draft=d1");
    });

    it("saves the current choice under a name", async () => {
        window.location.hash = "#/compare?left=a1&right=b2";
        stubFetch({ ...BOTH, "/api/compare-drafts": { items: [], max: 4 } });
        render(Compare);
        const input = await screen.findByLabelText("Draft name");
        await fireEvent.input(input, { target: { value: "Phones" } });
        await fireEvent.click(screen.getByRole("button", { name: "Save" }));
        await waitFor(() => {
            const call = (fetch as ReturnType<typeof vi.fn>).mock.calls.find(
                ([, init]) => init?.method === "POST",
            );
            expect(call?.[0]).toBe("/api/compare-drafts");
            expect(JSON.parse(call?.[1].body)).toEqual({
                name: "Phones", lookup_ids: ["a1", "b2"],
            });
        });
    });

    it("cannot save without two checks and a name", async () => {
        window.location.hash = "#/compare";
        stubFetch({ ...BOTH, "/api/compare-drafts": { items: [], max: 4 } });
        render(Compare);
        await screen.findByLabelText("Draft name");
        expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    });
});


describe("Compare notes and questions (B193)", () => {
    beforeEach(() => {
        window.location.hash = "#/compare?left=a1&right=b2";
    });

    it("takes a note on one side's risk and sends it to the same store as the report",
        async () => {
            stubFetch({
                ...BOTH,
                "/api/lookups/a1/triage": { lookup_id: "a1", checked: [], notes: {} },
                "/api/lookups/b2/triage": { lookup_id: "b2", checked: [], notes: {} },
                "/api/lookups/a1/notes": {
                    lookup_id: "a1",
                    notes: { x: "seller says the belt was done at 90k" },
                },
            });
            render(Compare);
            await fireEvent.click(await screen.findByRole("button", { name: "T-x" }));
            // The claim is shared, so both columns carry a note field; the
            // reader writes against the first side here.
            const notes = await screen.findAllByLabelText(/Your note on this risk/);
            const note = notes[0];
            await fireEvent.input(note, {
                target: { value: "seller says the belt was done at 90k" },
            });
            await fireEvent.blur(note);
            await waitFor(() => {
                const call = (fetch as ReturnType<typeof vi.fn>).mock.calls.find(
                    ([path, init]) =>
                        path === "/api/lookups/a1/notes" && init?.method === "POST",
                );
                expect(call?.[0]).toBe("/api/lookups/a1/notes");
                expect(JSON.parse(call?.[1].body)).toEqual({
                    claim_key: "x",
                    note: "seller says the belt was done at 90k",
                });
            });
        });

    it("offers the ask-a-question box only for a saved draft", async () => {
        stubFetch({ ...BOTH, "/api/compare-drafts": { items: [], max: 4 } });
        render(Compare);
        await screen.findByRole("columnheader", { name: "One" });
        expect(screen.queryByLabelText("Question")).toBeNull();
        expect(
            screen.getByText(/Save this comparison as a draft/i),
        ).toBeInTheDocument();
    });

    it("asks the agent a question about an open draft and keeps the answer", async () => {
        window.location.hash = "#/compare?draft=d1&ids=a1,b2";
        stubFetch({
            ...BOTH,
            "/api/compare-drafts": { items: [DRAFT], max: 4 },
            "/api/compare-drafts/d1/questions": {
                items: [
                    {
                        draft_id: "d1", question_id: "q9",
                        question: "which is cheaper to fix?",
                        answer: "The first one: the chain is a known, cheap fix.",
                        job_id: "j1", asked_at: "", answered_at: "",
                    },
                ],
            },
        });
        render(Compare);
        expect(
            await screen.findByText("which is cheaper to fix?"),
        ).toBeInTheDocument();
        expect(
            screen.getByText("The first one: the chain is a known, cheap fix."),
        ).toBeInTheDocument();
        const box = screen.getByLabelText("Question");
        await fireEvent.input(box, { target: { value: "and the second?" } });
        await waitFor(() =>
            expect(screen.getByRole("button", { name: "Ask" })).toBeEnabled(),
        );
    });
});


describe("Compare board and first glance (B194)", () => {
    const DRAFTS = { ...BOTH, "/api/compare-drafts": { items: [DRAFT], max: 4 } };

    it("states each side's serious count before anything is opened", async () => {
        window.location.hash = "#/compare?left=a1&right=b2";
        stubFetch(BOTH);
        render(Compare);
        // Both sides carry one high claim in the fixture. The strip is one
        // line naming each side, so the assertion is on the line: each
        // label appears beside its own count.
        const strip = await screen.findByText(/1 serious/);
        expect(strip.textContent).toContain("One");
        expect(strip.textContent).toContain("Two");
        expect(strip.textContent).not.toContain("undefined");
    });

    it("offers the board only for a saved draft, and opens it centred", async () => {
        window.location.hash = "#/compare?draft=d1&ids=a1,b2";
        stubFetch({
            ...DRAFTS,
            "/api/compare-drafts/d1/board": {
                draft_id: "d1", strokes: [], notes: [], updated_at: "",
            },
        });
        render(Compare);
        const board = await screen.findByRole("button", { name: /Board/ });
        await fireEvent.click(board);
        expect(window.location.hash).toContain("board=1");
        expect(
            await screen.findByLabelText("Your marks over the comparison"),
        ).toBeInTheDocument();
    });

    it("does not offer the board without a draft", async () => {
        window.location.hash = "#/compare?left=a1&right=b2";
        stubFetch({ ...BOTH, "/api/compare-drafts": { items: [], max: 4 } });
        render(Compare);
        await screen.findByRole("columnheader", { name: "One" });
        expect(screen.queryByRole("button", { name: /Board/ })).toBeNull();
    });

    it("fills the ask box from a suggested question", async () => {
        window.location.hash = "#/compare?draft=d1&ids=a1,b2";
        stubFetch({
            ...DRAFTS,
            "/api/compare-drafts/d1/questions": { items: [] },
        });
        render(Compare);
        const suggestion = await screen.findByRole("button", {
            name: /fewest serious risks/,
        });
        await fireEvent.click(suggestion);
        const box = screen.getByLabelText("Question") as HTMLInputElement;
        expect(box.value).toBe("Which of these has the fewest serious risks?");
    });
});
