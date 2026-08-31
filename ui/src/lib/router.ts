import { readable } from "svelte/store";

export type Route = { name: string; params: string[] };

export const DEFAULT_ROUTE = "ask";

export function parseHash(hash: string): Route {
    const parts = hash
        .replace(/^#\/?/, "")
        .split("/")
        .filter(Boolean)
        .map(decodeURIComponent);
    if (!parts.length) return { name: DEFAULT_ROUTE, params: [] };
    return { name: parts[0], params: parts.slice(1) };
}

export const toHash = (name: string, ...params: string[]) =>
    `#/${[name, ...params].map(encodeURIComponent).join("/")}`;

export const navigate = (name: string, ...params: string[]) => {
    window.location.hash = toHash(name, ...params);
};

export const route = readable<Route>(
    parseHash(typeof window === "undefined" ? "" : window.location.hash),
    (set) => {
        const onChange = () => set(parseHash(window.location.hash));
        window.addEventListener("hashchange", onChange);
        return () => window.removeEventListener("hashchange", onChange);
    },
);
