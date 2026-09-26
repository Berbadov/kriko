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
