import { describe, expect, it } from "vitest";

// Vite's own glob rather than node:fs — this tsconfig ships no Node types, and
// asking for them to read four files in the same directory is the wrong trade.
const SHEETS = import.meta.glob("./*.css", {
    query: "?raw",
    import: "default",
    eager: true,
}) as Record<string, string>;

const names = () => Object.keys(SHEETS).map((path) => path.replace("./", ""));

// Comments are stripped first: the useful comments in these sheets are the ones
// naming the literal they replaced ("was #fff, which printed
// white-on-light-blue"), and a colour in a comment paints nothing.
const stripComments = (css: string) =>
    css.replace(/\/\*[\s\S]*?\*\//g, (block) => block.replace(/[^\n]/g, " "));

// A literal colour is how #e5e5e5 got into `.history` and #b3261e into
// `tr.concern`: both invisible in dark, both wrong in light. tokens.css is the
// one file allowed to name a colour; everything else asks for one.
const COLOUR = /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/;

describe("the stylesheets", () => {
    it("names a colour only in tokens.css", () => {
        const offenders: string[] = [];
        for (const [path, css] of Object.entries(SHEETS)) {
            const name = path.replace("./", "");
            if (name === "tokens.css") continue;
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
            "print.css",
            "tokens.css",
        ]);
    });

    it("loads no webfont — the app must render styled with no network", () => {
        const all = Object.values(SHEETS).join("\n");
        expect(all).not.toMatch(/@import|fonts\.googleapis|fonts\.gstatic/);
    });
});
