import { describe, expect, it } from "vitest";

// Vite's own glob rather than node:fs — this tsconfig ships no Node types, and
// asking for them to read four files in the same directory is the wrong trade.
const SHEETS = import.meta.glob("./**/*.css", {
    query: "?raw",
    import: "default",
    eager: true,
}) as Record<string, string>;

const names = () => Object.keys(SHEETS).map((path) => path.replace("./", ""));

const THEMES = Object.fromEntries(
    Object.entries(SHEETS).filter(([path]) => path.startsWith("./themes/")),
);

// Comments are stripped first: the useful comments in these sheets are the ones
// naming the literal they replaced ("was #fff, which printed
// white-on-light-blue"), and a colour in a comment paints nothing.
const stripComments = (css: string) =>
    css.replace(/\/\*[\s\S]*?\*\//g, (block) => block.replace(/[^\n]/g, " "));

// A literal colour is how #e5e5e5 got into `.history` and #b3261e into
// `tr.concern`: both invisible in dark, both wrong in light. tokens.css is the
// one file allowed to name a colour; everything else asks for one.
//
// print.css is the second exemption, for the opposite reason: paper has no
// theme, so a token that resolves against the screen's palette is the wrong
// value there by construction. It is exempt from *this* case only — the other
// three still read it.
const EXEMPT = new Set([
    "tokens.css",
    "print.css",
    ...Object.keys(THEMES).map((path) => path.replace("./", "")),
]);
const COLOUR = /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/;

describe("the stylesheets", () => {
    it("names a colour only in tokens.css, and in print.css on paper", () => {
        const offenders: string[] = [];
        for (const [path, css] of Object.entries(SHEETS)) {
            const name = path.replace("./", "");
            if (EXEMPT.has(name)) continue;
            stripComments(css)
                .split("\n")
                .forEach((line, i) => {
                    if (COLOUR.test(line)) offenders.push(`${name}:${i + 1}: ${line.trim()}`);
                });
        }
        expect(offenders).toEqual([]);
    });

    it("references no custom property it never defines", () => {
        const all = Object.values(SHEETS).join("\n");
        const defined = new Set([...all.matchAll(/(--[a-z0-9-]+)\s*:/g)].map((m) => m[1]));
        const used = new Set([...all.matchAll(/var\((--[a-z0-9-]+)/g)].map((m) => m[1]));
        expect([...used].filter((name) => !defined.has(name))).toEqual([]);
    });

    // Without this, deleting every sheet makes the checks above pass on an
    // empty list — which is how this test first "passed" before a single
    // stylesheet existed.
    it("is actually looking at the sheets", () => {
        expect(names().sort()).toEqual([
            "base.css",
            "components.css",
            "fonts.css",
            "print.css",
            "themes/lemonade.css",
            "themes/slate.css",
            "tokens.css",
        ]);
    });

    it("has more than one theme, or the split bought nothing", () => {
        expect(Object.keys(THEMES).length).toBeGreaterThan(1);
    });

    // The whole point of the split. A colour alias defined by one theme and
    // forgotten by the next is invisible until someone switches: the property
    // simply does not resolve and the element paints its inherited colour, or
    // nothing. Half a theme is worse than no theme, so it fails the build.
    it("defines every colour alias in every theme", () => {
        const aliases = new Set<string>();
        for (const css of Object.values(THEMES)) {
            for (const m of stripComments(css).matchAll(/(--[a-z0-9-]+)\s*:/g)) {
                aliases.add(m[1]);
            }
        }
        const missing: string[] = [];
        for (const [path, css] of Object.entries(THEMES)) {
            const defined = new Set(
                [...stripComments(css).matchAll(/(--[a-z0-9-]+)\s*:/g)].map((m) => m[1]),
            );
            for (const alias of aliases) {
                if (!defined.has(alias)) missing.push(`${path.replace("./", "")} lacks ${alias}`);
            }
        }
        expect(missing).toEqual([]);
    });

    // A component asks for `var(--panel)`; a theme is the only thing that
    // answers. If a theme is missing the answer the component renders unpainted,
    // which is the failure this whole file exists to prevent.
    it("answers every colour a component asks for, from every theme", () => {
        const asked = new Set(
            [...Object.entries(SHEETS)
                .filter(([path]) => !path.startsWith("./themes/") && path !== "./tokens.css")
                .map(([, css]) => css)
                .join("\n")
                .matchAll(/var\((--[a-z0-9-]+)/g)].map((m) => m[1]),
        );
        const structural = new Set(
            [...stripComments(SHEETS["./tokens.css"]).matchAll(/(--[a-z0-9-]+)\s*:/g)].map(
                (m) => m[1],
            ),
        );
        const unanswered: string[] = [];
        for (const [path, css] of Object.entries(THEMES)) {
            const defined = new Set(
                [...stripComments(css).matchAll(/(--[a-z0-9-]+)\s*:/g)].map((m) => m[1]),
            );
            for (const name of asked) {
                if (!structural.has(name) && !defined.has(name)) {
                    unanswered.push(`${path.replace("./", "")} cannot answer ${name}`);
                }
            }
        }
        expect(unanswered).toEqual([]);
    });

    it("loads no webfont — the app must render styled with no network", () => {
        const all = Object.values(SHEETS).join("\n");
        expect(all).not.toMatch(/@import|fonts\.googleapis|fonts\.gstatic/);
    });
});
