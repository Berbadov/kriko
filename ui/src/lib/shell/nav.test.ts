import { describe, expect, it } from "vitest";
import { ALL_ROUTES, NAV, groupsFor, isAuthorOnly } from "./nav";

describe("the route table", () => {
    it("gives a buyer exactly the group about using knowledge", () => {
        const groups = groupsFor("buyer");
        expect(groups.map((g) => g.title)).toEqual(["Check", "This install"]);
        expect(groups[0].items.map((i) => i.name)).toEqual([
            "check",
            "history",
            "compare",
            // The extension is the buyer's half of the product, so it sits
            // inside the one group they can see rather than behind the author
            // gate with the other setup screens.
            "extension",
        ]);
    });

    it("gives an author every group", () => {
        expect(groupsFor("author").map((g) => g.title)).toEqual([
            "Check",
            "Knowledge",
            "System",
            "This install",
        ]);
    });

    it("shows a buyer what version they are running", () => {
        // The person asked "which version are you on?" is usually the one who
        // cannot open the author screens, so About is not behind that gate.
        expect(isAuthorOnly("about")).toBe(false);
    });

    it("knows which routes a buyer may not open", () => {
        expect(isAuthorOnly("overview")).toBe(true);
        expect(isAuthorOnly("health")).toBe(true);
        expect(isAuthorOnly("check")).toBe(false);
        expect(isAuthorOnly("compare")).toBe(false);
        expect(isAuthorOnly("extension")).toBe(false);
    });

    it("lists every destination once, so App.svelte and the rail cannot drift", () => {
        expect(ALL_ROUTES).toEqual([
            "check",
            "history",
            "compare",
            "extension",
            "overview",
            "subjects",
            "coverage",
            "health",
            "packs",
            "jobs",
            "connect",
            "about",
        ]);
        expect(new Set(ALL_ROUTES).size).toBe(ALL_ROUTES.length);
        expect(NAV.length).toBe(4);
    });
});
