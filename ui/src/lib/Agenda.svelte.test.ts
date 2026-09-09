import { render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Agenda from "./Agenda.svelte";
import { stubFetch, stubFetchFailing } from "./stub-fetch";

const ROWS = {
    "/api/agenda": {
        rows: [
            {
                kind: "empty_subject",
                subject_id: "s1",
                pack_id: "p",
                label: "The asked-about one",
                why: "nothing known about it yet",
                asked: 3,
            },
            {
                kind: "unknown_subject",
                subject_id: "",
                pack_id: "p",
                label: "",
                identity: "a=1",
                why: "no subject exists for it",
                asked: 1,
            },
        ],
        note: "",
        window: 500,
        counts: {},
    },
};

describe("the agenda card", () => {
    it("shows the ordering before an agent acts on it", async () => {
        stubFetch(ROWS);
        render(Agenda);
        expect(await screen.findByText("The asked-about one")).toBeTruthy();
        expect(await screen.findByText("asked about 3×")).toBeTruthy();
        // The named tool, so the reader can tell this is the agent's list and
        // not a second one the app keeps for itself.
        expect(await screen.findByText("research_agenda")).toBeTruthy();
    });

    it("offers each row as a prompt for a harness this app cannot reach", async () => {
        const writeText = vi.fn(async (_text: string) => {});
        vi.stubGlobal("navigator", { clipboard: { writeText } });
        stubFetch(ROWS);
        render(Agenda);
        const buttons = await screen.findAllByText("Copy as a prompt");
        buttons[0].click();
        await vi.waitFor(() => expect(writeText).toHaveBeenCalled());
        expect(writeText.mock.calls[0][0]).toContain("The asked-about one");
    });

    it("stays a card rather than becoming a second error surface", async () => {
        // Connecting a harness is the job of this screen; an agenda that
        // could not be computed must not look like the connection failing.
        stubFetchFailing();
        render(Agenda);
        expect(await screen.findByText(/Connecting a harness still works/)).toBeTruthy();
    });

    it("says out loud when the ordering is worse than usual", async () => {
        stubFetch({
            "/api/agenda": { ...ROWS["/api/agenda"], note: "no analyses recorded yet" },
        });
        render(Agenda);
        expect(await screen.findByText("no analyses recorded yet")).toBeTruthy();
    });
});
