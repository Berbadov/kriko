import { fireEvent, render, screen } from "@testing-library/svelte";
import { describe, expect, it, vi } from "vitest";
import Activity from "./Activity.svelte";

/* The shell, not the three screens.
 *
 * Jobs, Pipeline and Submissions keep their own suites — they are rendered
 * here unchanged, and re-asserting their content would be testing them twice
 * while testing this file not at all. What is new is the lens: which of the
 * three is mounted, and whether a retired address still lands where it named.
 */

// Every route any of the three touches, answered emptily. A lens test must
// fail on the wrong screen being mounted, never on a stray fetch.
function stub() {
    vi.stubGlobal(
        "fetch",
        vi.fn(
            async () =>
                new Response(
                    JSON.stringify({
                        items: [],
                        runs: [],
                        submissions: [],
                        packs: [],
                        totals: {},
                    }),
                ),
        ),
    );
}

describe("Activity", () => {
    it("opens on runs, and offers the other two as lenses", async () => {
        stub();
        render(Activity, {});
        expect(await screen.findByRole("tablist", { name: "Activity" })).toBeInTheDocument();
        const runs = screen.getByRole("tab", { name: "Runs" });
        expect(runs).toHaveAttribute("aria-selected", "true");
        expect(screen.getByRole("tab", { name: /pipeline did/ })).toHaveAttribute(
            "aria-selected",
            "false",
        );
        expect(screen.getByRole("tab", { name: /researchers sent/ })).toBeInTheDocument();
    });

    it("lands on the lens a retired address named", async () => {
        // `#/submissions` is a link this app's own hints hand out. Resolving
        // it to Activity's *first* lens would be the reorganisation quietly
        // sending the reader to the wrong screen — worse than a 404, because
        // it looks like it worked.
        stub();
        render(Activity, { lens: "submissions" });
        expect(
            await screen.findByRole("tab", { name: /researchers sent/ }),
        ).toHaveAttribute("aria-selected", "true");
    });

    it("falls back to runs when handed a lens that does not exist", async () => {
        stub();
        render(Activity, { lens: "nonsense" });
        expect(await screen.findByRole("tab", { name: "Runs" })).toHaveAttribute(
            "aria-selected",
            "true",
        );
    });

    it("switches the mounted screen, not just the tab", async () => {
        stub();
        render(Activity, {});
        // Jobs owns this heading; Pipeline does not. Asserting on a heading
        // rather than on the tab state is the whole point — a tab strip that
        // highlights correctly and renders the same screen is the bug this
        // catches.
        expect(await screen.findByRole("heading", { name: /Runs/ })).toBeInTheDocument();
        await fireEvent.click(screen.getByRole("tab", { name: /pipeline did/ }));
        expect(screen.queryByRole("heading", { name: /^Runs$/ })).toBeNull();
    });
});
