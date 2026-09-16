import { describe, expect, it } from "vitest";
import {
    ALL_ROUTES,
    NAV,
    destinationsFor,
    groupsFor,
    isAuthorOnly,
    labelOf,
    resolve,
} from "./nav";

describe("the route table", () => {
    it("gives a buyer exactly the group about using knowledge", () => {
        const groups = groupsFor("buyer");
        expect(groups.map((g) => g.title)).toEqual(["Check", "This install"]);
        expect(groups[0].items.map((i) => i.name)).toEqual([
            "check",
            "history",
            "compare",
            "questions",
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
        expect(isAuthorOnly("knowledge")).toBe(true);
        expect(isAuthorOnly("console")).toBe(true);
        expect(isAuthorOnly("bench")).toBe(true);
        // Retired names keep the gate they had, because they resolve to a
        // route that has one.
        expect(isAuthorOnly("health")).toBe(true);
        expect(isAuthorOnly("coverage")).toBe(true);
        expect(isAuthorOnly("marks")).toBe(true);
        expect(isAuthorOnly("submissions")).toBe(true);
        expect(isAuthorOnly("check")).toBe(false);
        // A preference is not authoring: the reader who never opens an author
        // screen is still the one choosing the palette.
        expect(isAuthorOnly("settings")).toBe(false);
        expect(isAuthorOnly("compare")).toBe(false);
        expect(isAuthorOnly("extension")).toBe(false);
    });

    it("lists every destination once, so App.svelte and the rail cannot drift", () => {
        expect(ALL_ROUTES).toEqual([
            "check",
            "history",
            "compare",
            "questions",
            "extension",
            "overview",
            "knowledge",
            "packs",
            // Which listing sites can be read here, and the button that
            // teaches this installation one more.
            "sites",
            // Runs, Knowledge pipeline and What researchers sent became three
            // lenses on one screen; Console and Connect became two on
            // another. Five rail entries, two destinations — the names they
            // retired still resolve, asserted below.
            "activity",
            "agents",
            "bench",
            "settings",
            "about",
        ]);
        expect(new Set(ALL_ROUTES).size).toBe(ALL_ROUTES.length);
        expect(NAV.length).toBe(4);
    });

    it("keeps the rail short enough to read at a glance", () => {
        // Not an arbitrary number: this is the ratchet on the thing that
        // actually went wrong here twice. Nine screens became a rail of
        // fifteen entries because every new capability got a row, and a rail
        // nobody can scan is a rail whose grouping stopped paying for itself.
        // A new destination is welcome; a fifteenth is a design conversation.
        expect(ALL_ROUTES.length).toBeLessThanOrEqual(14);
    });

    it("still resolves every name the rail used to spell out", () => {
        // Each of these is a link something already hands out: `#/jobs` is
        // where a job-starting POST's own response points, `#/connect` is in
        // the first-run hints, `#/coverage` is in the browser extension.
        // Turning any of them into "No such view" is the reorganisation
        // breaking the reader's bookmarks to prove a point.
        expect(resolve("jobs")).toEqual({ name: "activity", lens: "runs" });
        expect(resolve("pipeline")).toEqual({ name: "activity", lens: "pipeline" });
        expect(resolve("submissions")).toEqual({
            name: "activity",
            lens: "submissions",
        });
        // Agents has one lens now — Connect — so neither name carries one.
        expect(resolve("console")).toEqual({ name: "agents" });
        expect(resolve("connect")).toEqual({ name: "agents" });
        // And they keep the author gate they had, because the screen that
        // absorbed them has one.
        for (const name of ["jobs", "pipeline", "submissions", "console", "connect"]) {
            expect(isAuthorOnly(name)).toBe(true);
        }
    });

    it("keeps the words a merged screen absorbed searchable", () => {
        // The palette searches these. "console" is deliberately not one any
        // more — it named an API-only prompt that a real terminal (reachable
        // from the rail, not through Agents) replaced, and searching it into
        // Agents now would send the reader to the wrong feature.
        const flat = destinationsFor("author");
        const agents = flat.find((d) => d.name === "agents");
        expect(agents?.also).toContain("connect");
        expect(agents?.also).not.toContain("console");
        expect(agents?.also).not.toContain("terminal");
        const activity = flat.find((d) => d.name === "activity");
        expect(activity?.also).toContain("jobs");
        expect(activity?.also).toContain("submissions");
    });

    // The palette renders this. Derived from the same table as the rail, so a
    // screen added to one is reachable by name in the other on the same day —
    // the failure being prevented is a palette quietly one release behind.
    it("flattens to exactly what the rail offers, with the group kept", () => {
        for (const mode of ["buyer", "author"] as const) {
            const flat = destinationsFor(mode);
            const groups = groupsFor(mode);
            expect(flat.map((d) => d.name)).toEqual(
                groups.flatMap((g) => g.items.map((i) => i.name)),
            );
            expect(new Set(flat.map((d) => d.group))).toEqual(
                new Set(groups.map((g) => g.title)),
            );
        }
    });

    it("names every route, following an alias, and never answers with nothing", () => {
        for (const name of ALL_ROUTES) {
            expect(labelOf(name).length).toBeGreaterThan(0);
            expect(labelOf(name)).not.toBe(name);
        }
        // An alias resolves to the label of the screen that absorbed it,
        // because that is the screen the reader is now looking at.
        expect(labelOf("coverage")).toBe("Browse");
        // An unknown route still announces as something. A live region handed
        // an empty string says nothing at all, which is the bug.
        expect(labelOf("nonsense")).toBe("nonsense");
    });
});
