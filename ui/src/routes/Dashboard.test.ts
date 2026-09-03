import { render, screen } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import { stubFetch, stubFetchFailing } from "../lib/stub-fetch";
import Dashboard from "./Dashboard.svelte";

const STATUS = {
    ok: true,
    packs: 2,
    enabled_packs: 1,
    counts: { subjects: 12, claims: 34 },
};

describe("Dashboard", () => {
    it("shows the store counts", async () => {
        stubFetch({ "/api/status": STATUS, "/api/activity": { items: [], malformed: 0 } });
        render(Dashboard);
        expect(await screen.findByText("34")).toBeInTheDocument();
        expect(await screen.findByText("Claims")).toBeInTheDocument();
    });

    it("says so when there is no activity, rather than showing an empty table", async () => {
        stubFetch({ "/api/status": STATUS, "/api/activity": { items: [], malformed: 0 } });
        render(Dashboard);
        expect(await screen.findByText(/No analysis activity yet/)).toBeInTheDocument();
    });

    it("surfaces a failure instead of rendering blank", async () => {
        stubFetchFailing();
        render(Dashboard);
        expect(await screen.findByText(/Could not load this view/)).toBeInTheDocument();
    });
});
