import { describe, expect, it } from "vitest";
import { rowFor } from "./mark";

/** A rail whose `.active` class is one navigation stale — which is precisely
 *  the DOM the old implementation measured against. */
function rail(active: string): HTMLElement {
    const nav = document.createElement("nav");
    nav.innerHTML = ["check", "history", "packs"]
        .map(
            (name) =>
                `<a class="nav-link${name === active ? " active" : ""}"
                    data-route="${name}" id="row-${name}">${name}</a>`,
        )
        .join("");
    return nav;
}

describe("the rail's marker", () => {
    it("follows the route, not a class a child has not re-rendered yet", () => {
        // The reader has navigated to `packs`; `NavGroup` has not caught up,
        // so `history` is still the row wearing `.active`. The old code
        // measured that row and drew the bar beside the wrong screen.
        const found = rowFor(rail("history"), "packs");
        expect(found?.id).toBe("row-packs");
    });

    it("agrees with the class when the class is current", () => {
        expect(rowFor(rail("packs"), "packs")?.id).toBe("row-packs");
    });

    it("falls back to the active row when the route has no row yet", () => {
        // One frame during a mode switch: the group holding the new route has
        // not mounted. One frame behind beats a marker that disappears.
        expect(rowFor(rail("history"), "submissions")?.id).toBe("row-history");
    });

    it("returns nothing when there is nothing to mark", () => {
        const empty = document.createElement("nav");
        expect(rowFor(empty, "check")).toBeNull();
    });
});
