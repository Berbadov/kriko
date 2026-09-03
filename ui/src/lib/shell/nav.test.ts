import { describe, expect, it } from "vitest";
import { ALL_ROUTES, NAV, groupsFor, isAuthorOnly } from "./nav";

describe("the route table", () => {
    it("gives a buyer exactly the group about using knowledge", () => {
        const groups = groupsFor("buyer");
        expect(groups.map((g) => g.title)).toEqual(["Check"]);
        expect(groups[0].items.map((i) => i.name)).toEqual([
            "check",
            "history",
            "compare",
        ]);
    });

    it("gives an author all three groups", () => {
        expect(groupsFor("author").map((g) => g.title)).toEqual([
            "Check",
            "Knowledge",
            "System",
        ]);
    });

    it("knows which routes a buyer may not open", () => {
        expect(isAuthorOnly("overview")).toBe(true);
        expect(isAuthorOnly("health")).toBe(true);
        expect(isAuthorOnly("check")).toBe(false);
        expect(isAuthorOnly("compare")).toBe(false);
    });

    it("lists every destination once, so App.svelte and the rail cannot drift", () => {
        expect(ALL_ROUTES).toEqual([
            "check",
            "history",
            "compare",
            "overview",
            "subjects",
            "coverage",
            "health",
            "packs",
            "jobs",
        ]);
        expect(new Set(ALL_ROUTES).size).toBe(ALL_ROUTES.length);
        expect(NAV.length).toBe(3);
    });
});
