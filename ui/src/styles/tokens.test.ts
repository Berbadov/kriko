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

const declarations = (css: string): Record<string, string> => Object.fromEntries(
    [...stripComments(css).matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)]
        .map(([, name, value]) => [name, value.trim()]),
);

function colour(tokens: Record<string, string>, name: string): string {
    const value = tokens[name];
    expect(value, name).toBeDefined();
    const alias = value.match(/^var\((--[a-z0-9-]+)\)$/);
    return alias ? colour(tokens, alias[1]) : value;
}

function luminance(hex: string): number {
    expect(hex).toMatch(/^#[0-9a-f]{6}$/i);
    const [r, g, b] = [1, 3, 5].map((start) => {
        const channel = parseInt(hex.slice(start, start + 2), 16) / 255;
        return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

const slate = SHEETS["./themes/slate.css"].split("@media");
const darkSlate = declarations(slate[0]);
const palettes = {
    panel: declarations(SHEETS["./themes/panel.css"]),
    lemonade: declarations(SHEETS["./themes/lemonade.css"]),
    "slate dark": darkSlate,
    "slate light": { ...darkSlate, ...declarations(slate[1]) },
};

describe.each(Object.entries(palettes))("navigation contrast in %s", (_name, tokens) => {
    it.each([
        ["--dim", "--n-1", 4.5],
        ["--text", "--panel-2", 4.5],
        ["--accent", "--accent-soft", 4.5],
        ["--accent-ink", "--accent", 4.5],
        ["--accent", "--n-1", 3],
    ] as const)("keeps %s legible against %s", (ink, ground, minimum) => {
        const a = luminance(colour(tokens, ink));
        const b = luminance(colour(tokens, ground));
        expect((Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)).toBeGreaterThanOrEqual(minimum);
    });
});

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
        // The content assertion is the load-bearing half. Vitest stubs CSS
        // modules to "" by default, and under that stub every rule in this file
        // passed on eight empty strings — a suite that reported green while
        // reading nothing. The names alone did not catch it: `import.meta.glob`
        // yields its keys either way.
        for (const [path, css] of Object.entries(SHEETS)) {
            expect(css.length, `${path} came back empty — is test.css on?`)
                .toBeGreaterThan(200);
        }
        expect(names().sort()).toEqual([
            "base.css",
            "components.css",
            "fonts.css",
            "motion.css",
            "print.css",
            "themes/lemonade.css",
            "themes/panel.css",
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

    // The same argument as the colour rule, one axis over: three components
    // each choosing their own 180ms is how an interface stops feeling like one
    // thing. motion.css is exempt for its keyframe percentages and the two
    // durations that have no token because nothing else may use them.
    it("names a duration or a curve only in tokens.css and motion.css", () => {
        const offenders: string[] = [];
        const TIMING = /\b\d+m?s\b|cubic-bezier\(/;
        for (const [path, css] of Object.entries(SHEETS)) {
            const name = path.replace("./", "");
            if (name === "tokens.css" || name === "motion.css") continue;
            stripComments(css)
                .split("\n")
                .forEach((line, i) => {
                    if (TIMING.test(line)) offenders.push(`${name}:${i + 1}: ${line.trim()}`);
                });
        }
        expect(offenders).toEqual([]);
    });

    // The blanket `animation-duration: 1ms !important` this replaced did not
    // honour the preference so much as break it: a skeleton stopped mid-pulse
    // and an entering panel froze at whatever opacity frame zero held. Every
    // animation must name its landed state.
    it("lands every animation on its end state under reduced motion", () => {
        const motion = stripComments(SHEETS["./motion.css"]);
        const animated = [...motion.matchAll(/\.([a-z-]+)\s*\{[^}]*animation:/g)].map(
            (m) => m[1],
        );
        expect(animated.length).toBeGreaterThan(2);

        const reduced = motion.slice(motion.indexOf("prefers-reduced-motion"));
        for (const name of animated) {
            expect(reduced, `.${name} keeps animating under reduced motion`).toContain(
                `.${name}`,
            );
        }
    });

    it("loads no webfont — the app must render styled with no network", () => {
        // Comments stripped: fonts.css explains this rule in prose, and a
        // sheet is not allowed to fail a check by describing it.
        const all = Object.values(SHEETS).map(stripComments).join("\n");
        expect(all).not.toMatch(/@import|fonts\.googleapis|fonts\.gstatic/);
    });
});
