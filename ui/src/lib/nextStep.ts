/** What this installation is missing, as one sentence and one link.
 *
 * A tour teaches the app in the order the app was built. This answers the
 * reader's actual question — "what now?" — from what the store currently holds,
 * which means it is right on the second run and the hundredth, and it goes
 * quiet on its own when there is nothing to say. There is no "seen the tour"
 * flag anywhere: the same reasoning as `firstRun` in App.svelte, one step on.
 *
 * The order below is a dependency order, not a priority list. An agent cannot
 * fill a gap in a pack that is not installed, and a check cannot run against a
 * store with no knowledge in it, so each step is the cheapest thing that
 * unblocks the next.
 */

export type Signals = {
    /** Packs installed in the engine's store. */
    packs: number;
    /** Packs enabled — an installed-but-disabled pack answers nothing. */
    enabled: number;
    /** Subjects a pack names but knows nothing about. */
    gaps: number;
    /** Harnesses wired to *this* store. A stale one is not connected. */
    agentsConnected: number;
    /** Harnesses this build knows how to write a config for. */
    agentsKnown: number;
    /** Pack updates waiting. */
    updatable: number;
    /** Checks this reader has ever run. */
    checks: number;
    /** Has a browser extension *ever* reached this app — not just recently.
     * Null when the build carries no extension to install, which is not a
     * step to suggest. Must come from `ExtensionStatus.ever_connected`, not
     * `.connected`: the latter is a live badge that goes false after a few
     * quiet hours, and this hint is asking a one-time question ("has this
     * ever been set up"), not a right-now one. */
    extensionConnected: boolean | null;
};

export type Step = {
    /** Stable id — the dismissal key, and what a test asserts on. */
    id: string;
    title: string;
    detail: string;
    /** Route name, resolved to a hash by the caller so this file stays pure. */
    route: string;
    action: string;
};

/** In dependency order — see the module comment. Each step is checked in
 * order and the first whose signal is true is offered. `authorOnly` says
 * whether the step's destination requires author mode: a buyer skips those
 * rather than being handed a link that only opens a "this is an author view"
 * gate, which was check-7 — the bar sending buyers to a dead end. */
type Candidate = Step & { authorOnly: boolean };

function candidates(s: Signals): Candidate[] {
    const list: Candidate[] = [];
    if (s.packs === 0)
        list.push({
            id: "install-pack",
            title: "The engine has no knowledge yet",
            detail: "A pack is what Kriko answers from. Nothing else here works until one is installed.",
            route: "packs",
            action: "Open Packs",
            authorOnly: true,
        });
    if (s.enabled === 0)
        list.push({
            id: "enable-pack",
            title: "Every installed pack is disabled",
            detail: "A disabled pack is still on disk but answers nothing, so a check returns no claims.",
            route: "packs",
            action: "Open Packs",
            authorOnly: true,
        });
    if (s.checks === 0)
        list.push({
            id: "first-check",
            title: "Run a check",
            detail: "Describe one thing you are about to buy and see what the installed packs already know about it.",
            route: "check",
            action: "New check",
            authorOnly: false,
        });
    // Above connecting an agent and below the first check, for the same
    // reason: the extension is what the reader came for — Kriko on the listing
    // they are actually looking at — while an agent is how the knowledge gets
    // maintained. Ask for the thing that pays off today first.
    if (s.extensionConnected === false)
        list.push({
            id: "install-extension",
            title: "Kriko is not on your listing pages yet",
            detail: "The browser extension reads the ad you are looking at and asks this app about that exact one. Adding it takes a minute.",
            route: "extension",
            action: "Add the extension",
            authorOnly: false,
        });
    // Only once the app has been used for what it is for. Connecting an agent
    // is how the knowledge grows, and that is a second question — asking it
    // before the first answer has been read is asking someone to maintain a
    // thing they have not yet seen work.
    if (s.agentsKnown > 0 && s.agentsConnected === 0)
        list.push({
            id: "connect-agent",
            title: "No agent can reach this store",
            detail: "Coverage gaps are filled by an agent holding the research protocol. Kriko can write the config itself.",
            route: "connect",
            action: "Connect an agent",
            authorOnly: true,
        });
    if (s.updatable > 0)
        list.push({
            id: "update-packs",
            title: `${s.updatable} pack update${s.updatable === 1 ? "" : "s"} waiting`,
            detail: "Knowledge moves weekly. Updating is a job, and it does not touch your history.",
            route: "packs",
            action: "Open Packs",
            authorOnly: true,
        });
    if (s.gaps > 0)
        list.push({
            id: "close-gaps",
            title: `${s.gaps} subject${s.gaps === 1 ? "" : "s"} with nothing known`,
            detail: "A pack names these but holds no claim for them. A connected agent can research them.",
            route: "coverage",
            action: "Open Coverage",
            authorOnly: true,
        });
    return list;
}

export function nextStep(s: Signals, mode: "buyer" | "author" = "author"): Step | null {
    const offered = candidates(s).find((c) => mode === "author" || !c.authorOnly);
    if (!offered) return null;
    const { authorOnly: _authorOnly, ...step } = offered;
    return step;
}
