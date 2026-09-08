import { describe, expect, it } from "vitest";

import { ApiError } from "./api";
import { remedyFor } from "./failure";

const at = (status: number, message = "boom") =>
    remedyFor(new ApiError(status, message));

describe("what a failure means to the reader", () => {
    it("reads a dead engine off a rejection that never had a status", () => {
        // `fetch` rejects rather than resolving when nothing is listening, so
        // this is the one failure with no status to switch on — and the most
        // common one, because the engine is a separate process that can die
        // while its window stays open.
        const remedy = remedyFor(new TypeError("Failed to fetch"));
        expect(remedy.headline).toMatch(/engine stopped answering/i);
        expect(remedy.next).toMatch(/open it again/i);
        expect(remedy.retryable).toBe(true);
    });

    it("keeps a non-Error rejection legible instead of printing [object]", () => {
        expect(remedyFor("just a string").technical).toBe("just a string");
    });

    it("does not offer a retry where trying again cannot help", () => {
        // A retry on a 404 is a button that has no path to working, and a
        // reader who presses it twice concludes the app is broken more deeply
        // than it is.
        expect(at(404).retryable).toBe(false);
        expect(at(403).retryable).toBe(false);
        expect(at(422).retryable).toBe(false);
    });

    it("sends a 409 to the screen that has the job it collided with", () => {
        const remedy = at(409);
        expect(remedy.route).toBe("jobs");
        expect(remedy.routeLabel).toBeTruthy();
        expect(remedy.retryable).toBe(true);
    });

    it("says a 5xx is ours, and where the log is", () => {
        const remedy = at(500);
        expect(remedy.headline).toMatch(/not something you did/i);
        expect(remedy.route).toBe("settings");
    });

    it("treats an unmapped 5xx the same as the one we named", () => {
        expect(at(503).headline).toBe(at(500).headline);
    });

    it("still has a remedy for a status nobody wrote a branch for", () => {
        // The fallback is the point: a status we never thought about must not
        // arrive on screen as a blank block.
        const remedy = at(418);
        expect(remedy.headline).toBeTruthy();
        expect(remedy.next).toBeTruthy();
    });

    it("keeps the exception rather than dropping it for the remedy", () => {
        // The remedy is what the reader needs; the exception is what we need
        // when the remedy did not work. Both, one folded away.
        expect(at(500, "table claims has no column x").technical).toContain(
            "no column x",
        );
    });

    it("names a next step on every branch", () => {
        for (const status of [400, 403, 404, 409, 422, 500, 503, 418]) {
            expect(at(status).next.length).toBeGreaterThan(20);
            expect(at(status).headline).not.toMatch(/error|exception/i);
        }
    });
});

// ── the gate that was missing ─────────────────────────────────────────
//
// B72 was not one bad sentence, it was seven views each inventing its own —
// which is what a per-view error string always becomes. The remedy now comes
// off the status in one module, and this is what keeps the eighth view from
// hand-rolling its own again.

const SOURCES = import.meta.glob("../**/*.svelte", {
    query: "?raw",
    import: "default",
    eager: true,
}) as Record<string, string>;

describe("no view writes its own error copy", () => {
    it("finds the components it is scanning", () => {
        // A glob that matches nothing passes every assertion below.
        expect(Object.keys(SOURCES).length).toBeGreaterThan(20);
    });

    it("nobody prints an exception at the reader", () => {
        // `{error.message}` and `{(e as Error).message}` in markup are the
        // shape of the bug: accurate, and the whole of what the reader gets.
        const offenders = Object.entries(SOURCES).filter(
            ([path, source]) =>
                !path.endsWith("/Failure.svelte")
                && /\{[^{}]*\b(?:e|err|error|cause)\.message\b[^{}]*\}/.test(
                    stripMarkupComments(source).split("</script>").pop() ?? "",
                ),
        );
        expect(offenders.map(([path]) => path)).toEqual([]);
    });

    it("the old sentence is gone and stays gone", () => {
        const offenders = Object.entries(SOURCES)
            .filter(([, source]) =>
                /Could not load this view:/.test(stripMarkupComments(source)),
            )
            .map(([path]) => path);
        expect(offenders).toEqual([]);
    });
});

// Async.svelte's comment names the copy it replaced, and a comment renders
// nothing — the same exemption tokens.test.ts makes for the same reason.
const stripMarkupComments = (source: string) =>
    source.replace(/<!--[\s\S]*?-->/g, "").replace(/\/\*[\s\S]*?\*\//g, "");
