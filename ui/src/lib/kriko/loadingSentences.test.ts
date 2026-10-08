/* Every loading sentence carries the jack mark.
 *
 * A loader is a screen-level "wait" sentence. Written as `class="state
 * loading"` with nothing beside it, it is the one kind of wait the design
 * system's mark is meant to replace, so this reads the source and fails on any
 * such sentence. Buttons that say "Starting…" while busy are button states,
 * not loaders, and are not matched here.
 */
import { describe, expect, it } from "vitest";

const COMPONENTS = import.meta.glob("../../**/*.svelte", {
    query: "?raw",
    import: "default",
    eager: true,
}) as Record<string, string>;

describe("loading sentences", () => {
    it("reads the whole component tree, so the guard cannot pass on nothing", () => {
        expect(Object.keys(COMPONENTS).length).toBeGreaterThan(50);
    });

    it("carries the jack mark wherever a screen says it is loading", () => {
        const bare: string[] = [];
        for (const [path, source] of Object.entries(COMPONENTS)) {
            source.split("\n").forEach((line, i) => {
                if (/class="state loading"/.test(line)) bare.push(`${path}:${i + 1}`);
            });
        }
        expect(bare).toEqual([]);
    });
});
