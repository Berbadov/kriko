import type { Mode } from "../mode";

export type NavItem = { name: string; label: string };
export type NavGroupSpec = { title: string; items: NavItem[]; authorOnly: boolean };

/** The destinations, grouped by verb.
 *
 * Nine tabs in one row said only "the backend has nine capabilities". The
 * groups are the three things someone does here: use the knowledge, grow it,
 * and mind the machine. `Health` sits under Knowledge rather than System
 * because it is about claim quality, not about this process.
 *
 * One table, read by both the rail and App.svelte's guard, so a route cannot
 * appear in one and not the other.
 */
export const NAV: NavGroupSpec[] = [
    {
        title: "Check",
        authorOnly: false,
        items: [
            { name: "check", label: "New check" },
            { name: "history", label: "History" },
            { name: "compare", label: "Compare" },
        ],
    },
    {
        title: "Knowledge",
        authorOnly: true,
        items: [
            { name: "overview", label: "Overview" },
            { name: "subjects", label: "Subjects" },
            { name: "coverage", label: "Coverage" },
            { name: "health", label: "Health" },
        ],
    },
    {
        title: "System",
        authorOnly: true,
        items: [
            { name: "packs", label: "Packs" },
            { name: "jobs", label: "Runs" },
        ],
    },
    {
        // Not author-only: "what version are you running" is asked of the
        // reader who cannot open the author screens, and it is the first
        // question any support exchange starts with.
        title: "This install",
        authorOnly: false,
        items: [{ name: "about", label: "About" }],
    },
];

export const groupsFor = (mode: Mode): NavGroupSpec[] =>
    NAV.filter((group) => mode === "author" || !group.authorOnly);

export const ALL_ROUTES: string[] = NAV.flatMap((group) =>
    group.items.map((item) => item.name),
);

const AUTHOR_ROUTES = new Set(
    NAV.filter((group) => group.authorOnly).flatMap((group) =>
        group.items.map((item) => item.name),
    ),
);

export const isAuthorOnly = (name: string): boolean => AUTHOR_ROUTES.has(name);
