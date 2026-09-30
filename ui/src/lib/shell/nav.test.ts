import { describe, expect, it } from "vitest";
import { DEFAULT_ROUTE } from "../router";
import * as navModule from "./nav";
import {
    ALL_ROUTES,
    NAV,
    destinations,
    labelOf,
    resolve,
} from "./nav";

describe("the route table", () => {
    it("gives everyone every group, and none of them is gated (B165)", () => {
        expect(NAV.map((g) => g.title)).toEqual([
            "Check",
            "Knowledge",
            "System",
            "This install",
        ]);
        // The gate is gone from the type as well as from the rail.
        for (const group of NAV) expect("authorOnly" in group).toBe(false);
        expect("isAuthorOnly" in navModule).toBe(false);
        expect("groupsFor" in navModule).toBe(false);
    });

    it("has no New check and no Question sheet (B163)", () => {
        expect(ALL_ROUTES).not.toContain("check");
        expect(ALL_ROUTES).not.toContain("questions");
        expect(NAV[0].items.map((i) => i.name)).toEqual(["history", "compare", "extension"]);
    });

    it("opens on Activity, and the old New check address lands there (B163)", () => {
        expect(DEFAULT_ROUTE).toBe("activity");
        expect(resolve("check")).toEqual({ name: "activity" });
        expect(ALL_ROUTES).toContain(resolve(DEFAULT_ROUTE).name);
    });

    it("lists every destination once, so App.svelte and the rail cannot drift", () => {
        expect(ALL_ROUTES).toEqual([
            "history",
            "compare",
            "extension",
            "overview",
            "knowledge",
            // Packs is a section at the top of Browse now (B167); `#/packs`
            // still resolves, asserted below.
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
    });

    it("lands #/packs and #/marks on Browse, since neither is a screen any more (B166, B167)", () => {
        expect(resolve("packs")).toEqual({ name: "knowledge", lens: "all" });
        expect(resolve("marks")).toEqual({ name: "knowledge", lens: "all" });
        // Both keep Browse's author gate.
        expect(isAuthorOnly("packs")).toBe(true);
        expect(isAuthorOnly("marks")).toBe(true);
    });

    it("keeps the words a merged screen absorbed searchable", () => {
        // The palette searches these. "console" is deliberately not one any
        // more — it named an API-only prompt that a real terminal (reachable
        // from the rail, not through Agents) replaced, and searching it into
        // Agents now would send the reader to the wrong feature.
        const flat = destinations();
        const agents = flat.find((d) => d.name === "agents");
        expect(agents?.also).toContain("connect");
        expect(agents?.also).not.toContain("console");
        expect(agents?.also).not.toContain("terminal");
        const activity = flat.find((d) => d.name === "activity");
        expect(activity?.also).toContain("jobs");
        expect(activity?.also).toContain("submissions");
    });

    // shell-8: the router's ALIASES table accepted "coverage" and "health"
    // long before the palette's `also` lists did, so typing either word (the
    // rail used to say Coverage and Health outright) turned up nothing. The
    // alias table is now the source both read from, so a name added there is
    // findable from the day it resolves.
    it("makes every alias the router accepts findable in the palette too", () => {
        const flat = destinations();
        const knowledge = flat.find((d) => d.name === "knowledge");
        expect(knowledge?.also).toContain("coverage");
        expect(knowledge?.also).toContain("health");
        expect(knowledge?.also).toContain("subjects");
        expect(knowledge?.also).toContain("marks");
    });

    // The palette renders this. Derived from the same table as the rail, so a
    // screen added to one is reachable by name in the other on the same day —
    // the failure being prevented is a palette quietly one release behind.
    it("flattens to exactly what the rail offers, with the group kept", () => {
        const flat = destinations();
        expect(flat.map((d) => d.name)).toEqual(
            NAV.flatMap((g) => g.items.map((i) => i.name)),
        );
        expect(new Set(flat.map((d) => d.group))).toEqual(new Set(NAV.map((g) => g.title)));
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
