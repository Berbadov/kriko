/* Every section heading carries a symbol (B159: "Use symbols for sections").
 *
 * The rule is about markup, so it is held against the markup. A heading added
 * next month without an `<Icon>` fails here instead of shipping bare, which is
 * how the rule stays true without anyone re-reading fourteen screens.
 *
 * What counts as a section heading: an `<h2>` or `<h3>` whose first content is
 * words. A heading that opens with an expression (`{claim.title}`, `{pack.name}`,
 * `{run.subject}`) names a *record*, a card the data supplied, and a glyph in
 * front of a claim's own title would say the app drew it. That exemption is by
 * shape, not by a list of files, so a new record card needs no entry anywhere.
 * `<h4>` is a caption inside a section and is not held to it.
 */
import { describe, expect, it } from "vitest";
import { NAV } from "./shell/nav";

const SOURCES = import.meta.glob("../**/*.svelte", {
    query: "?raw",
    import: "default",
    eager: true,
}) as Record<string, string>;

const ICONS = SOURCES["./Icon.svelte"] ?? "";

/** The names `Icon.svelte` can draw, read off its table rather than listed
 *  here, so a glyph added there is usable here the same day. */
const GLYPHS = new Set([...ICONS.matchAll(/^ {8}([a-z]+):\s*\[/gm)].map((m) => m[1]));

/** Screens another PR owns while this one is open. Sites.svelte is being
 *  rebuilt by B181, and editing its headings here would collide with that
 *  work; the entry goes when that lands. */
const PENDING = new Set(["../routes/Sites.svelte"]);

const markup = (source: string) =>
    source.replace(/<!--[\s\S]*?-->/g, "").replace(/\/\*[\s\S]*?\*\//g, "");

type Heading = { file: string; tag: string; text: string; body: string };

const headings: Heading[] = [];
for (const [file, source] of Object.entries(SOURCES)) {
    for (const m of markup(source).matchAll(/<(h[23])\b[^>]*>([\s\S]*?)<\/\1>/g)) {
        const body = m[2];
        if (body.trimStart().startsWith("{")) continue;
        headings.push({
            file,
            tag: m[1],
            body,
            text: body.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim(),
        });
    }
}

describe("section headings", () => {
    // A glob that matches nothing, or a regex that has stopped matching,
    // satisfies every assertion below it.
    it("found the screens, the glyph table and a good many headings", () => {
        expect(ICONS.length).toBeGreaterThan(1000);
        expect(GLYPHS.size).toBeGreaterThan(30);
        expect(headings.length).toBeGreaterThan(40);
    });

    it("all carry a symbol", () => {
        const bare = headings
            .filter((h) => !PENDING.has(h.file) && !/<Icon\b/.test(h.body))
            .map((h) => `${h.file}: <${h.tag}> ${h.text}`);
        expect(bare).toEqual([]);
    });

    it("draw a symbol the table actually has", () => {
        // An unknown name renders an empty box, which reads as a heading whose
        // glyph failed to load. It is the failure Icon.svelte chose to make
        // visible to us and invisible to the reader, so it is checked here.
        const unknown: string[] = [];
        for (const h of headings) {
            for (const m of h.body.matchAll(/<Icon\b[^>]*\bname="([^"]+)"/g)) {
                if (!GLYPHS.has(m[1])) unknown.push(`${h.file}: ${h.text} -> ${m[1]}`);
            }
        }
        expect(unknown).toEqual([]);
    });
});

describe("the rail's group titles", () => {
    it("each name a symbol the table has, and no two share one", () => {
        const symbols = NAV.map((group) => group.symbol);
        for (const group of NAV) {
            expect(GLYPHS.has(group.symbol), `${group.title} -> ${group.symbol}`).toBe(true);
        }
        expect(new Set(symbols).size).toBe(symbols.length);
    });
});
