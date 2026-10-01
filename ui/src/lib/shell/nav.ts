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
/** `symbol` is a name in `lib/Icon.svelte`'s table: every group title in the
 *  rail carries one (B159, "Use symbols for sections"), and a required field is
 *  what makes a group added later fail the type check instead of shipping bare. */
export type NavGroupSpec = {
    title: string;
    symbol: string;
    items: NavItem[];
    /** The title is a tab that folds its rows (B167). Two groups only:
     *  Check and This install are short and the reader's own, and a fold on
     *  them would hide the first thing they came for. */
    foldable?: boolean;
};

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
        symbol: "verify",
        items: [
            // No "New check" and no "Question sheet" (B163): the browser
            // extension is where a check starts, and what it finds is read on
            // the result. History and Compare are what is left of the group.
            // Run is where a run over a whole category starts and is watched
            // (B175, B176); it was the top of Activity's Runs lens.
            // Home is where the app opens (B174): graphs of checks, knowledge
            // gained and research spend. The detail is under Activity.
            { name: "home", label: "Home", also: ["welcome", "dashboard", "graphs"] },
            { name: "run", label: "Run", also: ["start", "author", "new pack", "agent run"] },
            // B193: several subjects picked first, then researched one
            // after another by the one worker every job already shares.
            { name: "queue", label: "Queue", also: ["queue up", "batch", "several products", "research queue"] },
            { name: "history", label: "History" },
            { name: "compare", label: "Compare" },
            { name: "extension", label: "Browser extension" },
        ],
    },
    {
        title: "Knowledge",
        symbol: "layers",
        foldable: true,
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
            // Installed catalogs are the section at its top (B167), so the
            // words for them find it: "packs" is an alias below.
            { name: "knowledge", label: "Browse", also: ["catalog", "catalogs", "install"] },
        ],
    },
    {
        title: "System",
        symbol: "server",
        foldable: true,
        items: [
            // Sites: what this installation can read. The words somebody
            // would type for it are all about the browser.
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
        title: "This install",
        symbol: "monitor",
        items: [
            // Preferences before facts: a reader in this group is more often
            // changing something than quoting a version, and the theme
            // switcher was previously a heading two thirds of the way down
            // About — findable only by someone who already knew.
            { name: "local", label: "Local LLM", also: ["ollama", "local plane", "local machine"] },
            { name: "settings", label: "Settings" },
            { name: "about", label: "About" },
        ],
    },
];

export const ALL_ROUTES: string[] = NAV.flatMap((group) =>
    group.items.map((item) => item.name),
);

/** Routes that no longer have a rail entry but must still resolve.
 *
 * A link is forever: the browser extension, a bookmark, and this app's own
 * older `NextStep` hints all point at `#/coverage`. Retiring a tab must not
 * turn those into "No such view" — they land on the lens that absorbed them.
 */
export type Alias = { name: string; lens?: string; catalogs?: boolean };
export const ALIASES: Record<string, Alias> = {
    subjects: { name: "knowledge", lens: "all" },
    // Singular, and it carries an id: `#/subject/<id>` is what the browser
    // panel's search builds. The plural above is the unfiltered list.
    subject: { name: "knowledge", lens: "all" },
    coverage: { name: "knowledge", lens: "gaps" },
    health: { name: "knowledge", lens: "weak" },
    // What readers said is not a lens any more (B166): the extension still
    // posts marks, and they still feed research signals, but nothing on
    // screen lists them. The address lands on Browse rather than on nothing.
    marks: { name: "knowledge", lens: "all" },
    // Packs became the section at the top of Browse (B167).
    // `catalogs` opens the folded line there (B180), so the old address still
    // lands on the installed packs.
    packs: { name: "knowledge", lens: "all", catalogs: true },
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
    // New check is gone (B163) and the app opens on Home (B174); an old
    // `#/check` bookmark lands on the same place.
    // `#/questions` is not here because it can carry an id: router.ts's
    // `parseHash` sends it to the result or to History.
    check: { name: "home" },
};

/** The route a name actually renders, following one alias hop. */
export const resolve = (name: string): Alias =>
    ALIASES[name] ?? { name };


/** Every destination as one flat list, with the group it sits under.
 *
 * The rail renders groups; a palette renders a list. Derived from the same
 * table rather than written twice, so a screen added to the rail is reachable
 * by name on the day it appears — a palette that has to be told about a new
 * route is a palette that is quietly one release behind.
 */
/** The alias words that resolve to a route, on top of whatever the item
 * already listed under `also`.
 *
 * ALIASES is the router's table, hand-maintained for the handful of retired
 * names that must still open something; `also` is the palette's search
 * vocabulary, hand-maintained for words that were never routes at all
 * ("console"). The two lists drift apart the moment a name is added to one
 * and not the other — that is shell-8: `coverage` and `health` open fine by
 * URL but were unfindable by typing them here. Deriving every alias key that
 * resolves to a route folds ALIASES into the search vocabulary instead of
 * asking someone to keep both current by hand.
 */
// "console" resolves by URL (a bookmark to the old screen must still open
// something) but is deliberately excluded from the palette's vocabulary: it
// named an API-only prompt that a real terminal replaced, and finding Agents
// by typing "console" would tell the reader a feature is here that is not.
// Every other alias word is fair game — the retirement was of the *screen*,
// not of the word someone reaching for it remembers.
const NOT_SEARCH_VOCABULARY = new Set(["console"]);

const aliasWordsFor = (name: string): string[] =>
    Object.entries(ALIASES)
        .filter(([word, target]) => target.name === name && !NOT_SEARCH_VOCABULARY.has(word))
        .map(([word]) => word);

export const destinations = (): {
    name: string;
    label: string;
    group: string;
    also?: string[];
}[] =>
    NAV.flatMap((group) =>
        group.items.map((item) => ({
            ...item,
            group: group.title,
            also: [...new Set([...(item.also ?? []), ...aliasWordsFor(item.name)])],
        })),
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
