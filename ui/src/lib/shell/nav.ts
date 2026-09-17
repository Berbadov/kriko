import type { Mode } from "../mode";

/** A destination, and the words a reader might reach for that are not its
 *  label.
 *
 * `also` exists because merging screens loses vocabulary. "Console" was a rail
 * entry for six versions; it is a lens on Agents now, and someone who reaches
 * for the palette and types `console` must still land on it. Without this the
 * reorganisation makes the app *harder* to search than it was — the reader is
 * punished for remembering the old name, which is exactly backwards.
 *
 * Search-only. It never renders, and it is not a route: an address is
 * `ALIASES`' job. */
export type NavItem = { name: string; label: string; also?: string[] };
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
            // Sites, next to Packs, because they are the same kind of thing
            // from the reader's side: what this installation can read. The
            // words somebody would type for it are all about the browser.
            { name: "sites", label: "Sites",
              also: ["adapter", "adapters", "website", "extension site", "register"] },
            // Three entries where there were three screens — Runs, Knowledge
            // pipeline, What researchers sent — and the same mistake Subjects
            // / Coverage / Health made. They are not three places: they are
            // one question, "what has this installation been doing", asked at
            // three depths. A run says whether long work is going and what it
            // printed; the pipeline says what it *did*, sources read and
            // findings refused; submissions say what arrived through the agent
            // door. A reader chasing "did my research actually land" had to
            // visit all three and hold the answer in their head.
            { name: "activity", label: "Activity", also: ["runs", "jobs", "pipeline", "submissions", "researchers", "log", "live", "operations", "feed", "mcp"] },
            // Console used to be a lens here, driving the same API a harness
            // does by hand. An embedded terminal replaced it and has since
            // been removed (§2.9); the shell that survives is `kriko tui`'s
            // pass-through, which is not a destination in this app at all —
            // so neither word is a searchable synonym for Agents any more.
            { name: "agents", label: "Agents", also: ["connect", "mcp", "harness", "claude"] },
            { name: "bench", label: "Benchmark",
              also: ["hallucination", "cost per claim", "protocols", "grading", "b126"] },
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
export const ALIASES: Record<string, { name: string; lens?: string }> = {
    subjects: { name: "knowledge", lens: "all" },
    // Singular, and it carries an id: `#/subject/<id>` is what the browser
    // panel's search builds. The plural above is the unfiltered list.
    subject: { name: "knowledge", lens: "all" },
    coverage: { name: "knowledge", lens: "gaps" },
    health: { name: "knowledge", lens: "weak" },
    marks: { name: "knowledge", lens: "marked" },
    // The five names the System group used to spell out. Every one of them is
    // a link something already hands out — `#/jobs` is what a POST's own
    // response points at, `#/connect` is in the first-run hints — so they
    // resolve to the lens that absorbed them rather than to "No such view".
    jobs: { name: "activity", lens: "runs" },
    pipeline: { name: "activity", lens: "pipeline" },
    submissions: { name: "activity", lens: "submissions" },
    // The feed's own names. "What is my agent doing" is the question people
    // will type, and neither word is a route (B122).
    operations: { name: "activity", lens: "live" },
    live: { name: "activity", lens: "live" },
    // Agents has one lens now — Connect — so neither name needs one.
    console: { name: "agents" },
    connect: { name: "agents" },
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
): { name: string; label: string; group: string; also?: string[] }[] =>
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
