/** Every link this app writes points at a view this app has.
 *
 * The onboarding path is real — `Welcome` on an empty store, `NextStep`
 * afterwards, and an `EmptyState` on most screens whose whole job is to hand
 * the reader the next place to go. What none of that had was a check that the
 * place exists. The audit's F10 names the symptom: the Packs empty state
 * pointed at a route that had to be corrected once already, by hand, after
 * someone clicked it.
 *
 * A dead link in onboarding is the worst dead link in the product. It is the
 * reader's first minute, they have no model of the app yet to tell them the
 * app is wrong rather than they are, and what they get is "No such view" —
 * which is indistinguishable from a broken install.
 *
 * So this walks the source for every destination anyone writes down and asks
 * whether `App.svelte` would render it. Three spellings, because there are
 * three: a literal `#/name` in markup, a `toHash`/`hashWith` call, and a route
 * name handed to `NextStep`. Nothing here is a list of routes — the renderable
 * set is read off `nav.ts` and off `App.svelte`'s own if-chain, so retiring a
 * route turns its links red the moment it goes.
 */

import { describe, expect, it } from "vitest";
import { ALIASES, ALL_ROUTES, resolve } from "./shell/nav";
import { DEFAULT_ROUTE } from "./router";

const SOURCES = import.meta.glob("../**/*.{svelte,ts}", {
    query: "?raw",
    import: "default",
    eager: true,
}) as Record<string, string>;

const APP = Object.entries(SOURCES).find(([path]) => path.endsWith("App.svelte"))?.[1] ?? "";

/** The names `App.svelte` will actually render.
 *
 * Read off the if-chain rather than listed, because the parametric views
 * (`result`, and whatever joins it) have no rail entry and would otherwise
 * have to be exempted by hand — an exemption list is the thing this file
 * exists to avoid.
 */
const rendered = new Set<string>([
    ...ALL_ROUTES,
    ...Object.keys(ALIASES),
    DEFAULT_ROUTE,
    ...[...APP.matchAll(/\.name === "([a-z][a-z0-9-]*)"/g)].map((m) => m[1]),
]);

const renders = (name: string): boolean =>
    rendered.has(name) || rendered.has(resolve(name).name);

/** Sources, minus the comments — this file's own prose names dead routes on
 *  purpose, and so does the odd explanatory comment elsewhere. */
const code = (source: string) =>
    source.replace(/<!--[\s\S]*?-->/g, "").replace(/\/\*[\s\S]*?\*\//g, "").replace(/\/\/.*/g, "");

type Link = { where: string; name: string; how: string };

const links: Link[] = [];
for (const [path, source] of Object.entries(SOURCES)) {
    if (path.includes(".test.")) continue;
    const body = code(source);
    const where = path.replace(/^\.\.\//, "");
    for (const [, name] of body.matchAll(/["'`]#\/([a-z][a-z0-9-]*)/g))
        links.push({ where, name, how: "a literal hash" });
    // `toHash(name, ...)` names the route first; `hashWith(query, name, ...)`
    // names it after the query object — and the query may itself hold quoted
    // strings (`author: "new"`), which are values, not views. One regex for
    // both read "new" as a route the app never renders.
    for (const [, name] of body.matchAll(/toHash\(\s*["']([a-z][a-z0-9-]*)["']/g))
        links.push({ where, name, how: "a hash built in code" });
    for (const [, name] of body.matchAll(/hashWith\(\{[^}]*\}[^)]*?["']([a-z][a-z0-9-]*)["']/g))
        links.push({ where, name, how: "a hash built in code" });
    if (path.endsWith("nextStep.ts"))
        for (const [, name] of body.matchAll(/^\s+route: "([a-z][a-z0-9-]*)",$/gm))
            links.push({ where, name, how: "a next step" });
}

describe("the links this app writes", () => {
    // A glob that matches nothing satisfies every assertion below it, and a
    // regex that has stopped matching looks exactly like a codebase with no
    // links in it. Both are caught here rather than in a green run.
    it("found the app and the links in it", () => {
        expect(APP.length).toBeGreaterThan(1000);
        expect(links.length).toBeGreaterThan(10);
        expect(new Set(links.map((l) => l.how)).size).toBe(3);
    });

    it.each([...new Set(links.map((l) => l.name))])("#/%s is a view this app renders", (name) => {
        const written = links.filter((l) => l.name === name);
        expect(renders(name), `${name} is written as ${written[0].how} in ${written
            .map((l) => l.where)
            .join(", ")} and App.svelte renders no such view`).toBe(true);
    });

    // The onboarding steps get their own assertion rather than only riding
    // along above: the reader who meets a dead link there is the one least
    // equipped to work around it, and "some link somewhere is fine" is not
    // the claim worth holding.
    it("every onboarding step names a view", () => {
        const steps = links.filter((l) => l.how === "a next step");
        expect(steps.length).toBeGreaterThan(4);
        expect(steps.filter((s) => !renders(s.name))).toEqual([]);
    });
});

describe("the first screen a reader ever sees", () => {
    const welcome = Object.entries(SOURCES).find(([p]) => p.endsWith("Welcome.svelte"))?.[1] ?? "";

    it("is one of the sources being scanned", () => {
        expect(welcome).toContain("Kriko is installed");
    });

    // B72's rule, at the one place it matters most. An exception message on
    // the welcome screen is a reader's *first* sentence from this product,
    // and "TypeError: undefined is not an object" is a worse first sentence
    // than anything else the app could have said.
    it("does not print an exception at the reader", () => {
        expect(code(welcome)).not.toMatch(/\be(?:rr|rror)?\.message\b/);
    });
});
