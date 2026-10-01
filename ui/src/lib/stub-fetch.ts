import { vi } from "vitest";

type Failure = { status: number; body: string };

const isFailure = (value: unknown): value is Failure =>
    typeof value === "object" &&
    value !== null &&
    typeof (value as Failure).status === "number" &&
    typeof (value as Failure).body === "string";

/** Stub `fetch` by path prefix.
 *
 * Holds no fixture data on purpose: this file is not a `.test.ts`, so
 * `test_ui_contains_no_pack_vocabulary` greps it like production code. Pass
 * your own payloads from the test that needs them.
 */
export function stubFetch(routes: Record<string, unknown>): void {
    vi.stubGlobal(
        "fetch",
        vi.fn(async (path: string, init?: RequestInit) => {
            const method = (init?.method ?? "GET").toUpperCase();
            // A key may pin a method with a `METHOD:/path` prefix, so a PUT and
            // a GET on one path answer different payloads. Unprefixed keys match
            // every method, as they always did.
            const match = Object.keys(routes)
                .filter((route) => {
                    const pinned = /^([A-Za-z]+):/.exec(route);
                    if (!pinned) return path.startsWith(route);
                    return method === pinned[1].toUpperCase() && path.startsWith(route.slice(pinned[0].length));
                })
                .sort((a, b) => b.length - a.length)[0];
            // A pinned and an unprefixed key can both match; the pinned one
            // describes the request better, so it wins at equal length.
            const key = match ?? Object.keys(routes)
                .filter((route) => !/^[A-Za-z]+:/.test(route) && path.startsWith(route))
                .sort((a, b) => b.length - a.length)[0];
            if (!key) return new Response(`not stubbed: ${path}`, { status: 500 });
            const value = routes[key];
            // A route may name a failure instead of a payload — an unreadable
            // site is a 404 the view is supposed to explain, not an accident.
            if (isFailure(value)) {
                return new Response(value.body, { status: value.status });
            }
            return new Response(JSON.stringify(value));
        }),
    );
}

/** Every request fails — for the "surfaces a failure instead of rendering
 * blank" case that each view owes its reader. */
export function stubFetchFailing(status = 500): void {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("boom", { status })));
}
