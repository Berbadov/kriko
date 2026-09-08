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
            // The artifact the reader takes *out* of the app: the asks, in
            // order, big enough to read standing in front of the thing. It gets a
            // rail entry rather than living only behind a report link
            // because on inspection day it is the first screen they want,
            // and with no id it resolves to the newest saved answer.
            { name: "questions", label: "Question sheet" },
            // Not author-only, and in Check rather than System: the extension
            // is the reader's half of the product — the one who never opens
            // an author screen is exactly the one who needs it installed.
            { name: "extension", label: "Browser extension" },
        ],
    },
    {
        title: "Knowledge",
        authorOnly: true,
        items: [
            { name: "overview", label: "Overview" },
            // One destination where there were three. Subjects, Coverage and
            // Health were not three places — they were three questions about
            // the same list ("what is here", "what is missing", "what is
            // thin"), and splitting them by route made the reader guess which
            // tab held the thing they came to look up. They are lenses on the
            // Knowledge screen now; the old names still resolve, see
            // ALIASES below.
            // Labelled "Browse", not "Knowledge": the group is already
            // called Knowledge, and a link whose text repeats its own
            // heading tells the reader nothing about what clicking does.
            { name: "knowledge", label: "Browse" },
        ],
    },
    {
        title: "System",
        authorOnly: true,
        items: [
            { name: "packs", label: "Packs" },
            { name: "jobs", label: "Runs" },
            // Beside Runs, not inside it: a job says whether long work is
            // going and what it printed; the pipeline says what it *did* —
            // sources read, findings kept, refusals and why. A run that
            // gathered nothing and a run that lost everything at the
            // grounding check look identical in a job log.
            { name: "pipeline", label: "Knowledge pipeline" },
            // What came in through the agent door and what the gate did with
            // it. In System rather than Knowledge because it is about the
            // door, not about what is known — and it is the only place a
            // refusal is legible at all.
            { name: "submissions", label: "What researchers sent" },
            { name: "console", label: "Console" },
            { name: "connect", label: "Connect an agent" },
        ],
    },
    {
        // Not author-only: "what version are you running" is asked of the
        // reader who cannot open the author screens, and it is the first
        // question any support exchange starts with.
        title: "This install",
        authorOnly: false,
        items: [
            // Preferences before facts: a reader in this group is more often
            // changing something than quoting a version, and the theme
            // switcher was previously a heading two thirds of the way down
            // About — findable only by someone who already knew.
            { name: "settings", label: "Settings" },
            { name: "about", label: "About" },
        ],
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

/** Routes that no longer have a rail entry but must still resolve.
 *
 * A link is forever: the browser extension, a bookmark, and this app's own
 * older `NextStep` hints all point at `#/coverage`. Retiring a tab must not
 * turn those into "No such view" — they land on the lens that absorbed them,
 * and they keep the author gate they had, which is why this is read *through*
 * `isAuthorOnly` rather than beside it.
 */
export const ALIASES: Record<string, { name: string; lens: string }> = {
    subjects: { name: "knowledge", lens: "all" },
    coverage: { name: "knowledge", lens: "gaps" },
    health: { name: "knowledge", lens: "weak" },
    marks: { name: "knowledge", lens: "marked" },
};

/** The route a name actually renders, following one alias hop. */
export const resolve = (name: string): { name: string; lens?: string } =>
    ALIASES[name] ?? { name };

export const isAuthorOnly = (name: string): boolean =>
    AUTHOR_ROUTES.has(resolve(name).name);


/** Every destination as one flat list, with the group it sits under.
 *
 * The rail renders groups; a palette renders a list. Derived from the same
 * table rather than written twice, so a screen added to the rail is reachable
 * by name on the day it appears — a palette that has to be told about a new
 * route is a palette that is quietly one release behind.
 */
export const destinationsFor = (
    mode: Mode,
): { name: string; label: string; group: string }[] =>
    groupsFor(mode).flatMap((group) =>
        group.items.map((item) => ({ ...item, group: group.title })),
    );

/** What the rail calls a route. Falls back to the name so an aliased or
 *  unknown route still announces as something rather than as nothing. */
export const labelOf = (name: string): string => {
    const target = resolve(name).name;
    for (const group of NAV) {
        for (const item of group.items) {
            if (item.name === target) return item.label;
        }
    }
    return name;
};
