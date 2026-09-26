import { readable } from "svelte/store";

export type Route = {
    name: string;
    params: string[];
    query: Record<string, string>;
};

export const DEFAULT_ROUTE = "check";

/** A route segment can be anything a reader pastes into the address bar.
 * decodeURIComponent throws on a malformed %-escape, and an uncaught throw
 * here would blank the whole app (the store that renders the rail never
 * gets a value) — so a segment that doesn't decode is kept raw and falls
 * through to the ordinary "No such view" state instead. */
const decodeSegment = (segment: string): string => {
    try {
        return decodeURIComponent(segment);
    } catch {
        return segment;
    }
};

export function parseHash(hash: string): Route {
    const [path, search = ""] = hash.replace(/^#\/?/, "").split("?");
    const query = Object.fromEntries(new URLSearchParams(search));
    const parts = path.split("/").filter(Boolean).map(decodeSegment);
    if (!parts.length) return { name: DEFAULT_ROUTE, params: [], query };
    return { name: parts[0], params: parts.slice(1), query };
}

const path = (name: string, params: string[]) =>
    `#/${[name, ...params].map(encodeURIComponent).join("/")}`;

export const toHash = (name: string, ...params: string[]) => path(name, params);

/** A link that carries query state — the mode — into the next view.
 *
 * Kept explicit rather than folded into `toHash`, which would have to read the
 * live route to know what to preserve. A caller that wants the mode carried
 * says so; a caller that wants a bare link still gets one.
 */
export function hashWith(
    query: Record<string, string | undefined>,
    name: string,
    ...params: string[]
): string {
    const pairs = Object.entries(query).filter(([, v]) => v !== undefined && v !== "");
    if (!pairs.length) return path(name, params);
    const search = new URLSearchParams(pairs as [string, string][]);
    return `${path(name, params)}?${search}`;
}

export const navigate = (name: string, ...params: string[]) => {
    const { query } = parseHash(window.location.hash);
    window.location.hash = hashWith(query, name, ...params);
};

/** Replace one query value without leaving the current view or adding a
 * history entry — a mode switch is not a navigation. */
export function setQuery(key: string, value: string | undefined): void {
    const current = parseHash(window.location.hash);
    const next = hashWith(
        { ...current.query, [key]: value },
        current.name,
        ...current.params,
    );
    window.history.replaceState(null, "", next);
    window.dispatchEvent(new HashChangeEvent("hashchange"));
}

export const route = readable<Route>(
    parseHash(typeof window === "undefined" ? "" : window.location.hash),
    (set) => {
        const onChange = () => set(parseHash(window.location.hash));
        // Re-read on subscribe: the initial value above is a module-load
        // snapshot, and the hash can change between this module being imported
        // and the first component subscribing — main.ts imports before it
        // mounts. Without this, the store starts one navigation stale.
        onChange();
        window.addEventListener("hashchange", onChange);
        return () => window.removeEventListener("hashchange", onChange);
    },
);
