import { render, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";
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

    it("says there is nothing to compare with fewer than two stored answers", async () => {
        window.location.hash = "#/compare";
        stubFetch({ "/api/history": { items: [HISTORY["/api/history"].items[0]] } });
        render(Compare);
        expect(await screen.findByText(/two saved checks/i)).toBeInTheDocument();
    });
});
