import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { clearApiCache } from "./lib/api";

// api.ts memoizes status()/settings()/packs() for a few seconds (B145
// perf-1/uicode-4), which is invisible in the app (every screen it visits
// again is a fresh navigation, well past the TTL) but not in a test file,
// where several `it()`s can run inside that window and a later test would
// otherwise see an earlier test's stubbed `fetch` response replayed back at
// it. One global reset, rather than every suite that touches these
// endpoints remembering to add its own.
afterEach(() => {
    clearApiCache();
});

// jsdom has no canvas. The pipeline scene asks for a 2D context on mount, and
// jsdom would print "Not implemented" for every one of those. Answer null
// quietly instead: a component that draws must then cope with no context,
// and a test that does need to draw stubs its own context.
HTMLCanvasElement.prototype.getContext = (() =>
    null) as unknown as typeof HTMLCanvasElement.prototype.getContext;
