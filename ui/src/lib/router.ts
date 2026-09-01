import { readable } from "svelte/store";

export type Route = {
    name: string;
    params: string[];
    query: Record<string, string>;
};

export const DEFAULT_ROUTE = "check";

export function parseHash(hash: string): Route {
    const [path, search = ""] = hash.replace(/^#\/?/, "").split("?");
    const query = Object.fromEntries(new URLSearchParams(search));
    const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
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
        window.addEventListener("hashchange", onChange);
        return () => window.removeEventListener("hashchange", onChange);
    },
);
