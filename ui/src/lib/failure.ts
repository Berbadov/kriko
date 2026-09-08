import { ApiError } from "./api";

/** What a failed request means, and what the reader can do about it.
 *
 * B72: every error surface in this app named an exception. "Could not load
 * this view: ConnectionError" and "500: Internal Server Error" are both
 * accurate and both useless — the reader of a local app has no terminal, no
 * log viewer and nobody to page, so whatever the screen says is the entire
 * remedy available to them.
 *
 * Derived from the *status*, not from the view. A per-view table of error
 * copy would be twenty places to keep in step, and the twenty-first view
 * would ship with none — the same failure mode as a hand-enumerated list
 * anywhere else in this repo. HTTP statuses are a closed vocabulary that does
 * not grow with the product, which is exactly the exception the scalability
 * rule carves out.
 */
export type Remedy = {
    /** What happened, in the reader's terms rather than the exception's. */
    headline: string;
    /** The next action. Empty only when there genuinely is not one. */
    next: string;
    /** Whether trying the same thing again could plausibly work. A retry
     *  offered on a 404 is a button that cannot help, and a reader who
     *  presses it twice concludes the app is broken in some deeper way. */
    retryable: boolean;
    /** Where to go when the remedy is on another screen. */
    route?: string;
    routeLabel?: string;
    /** The exception itself, kept because a bug report needs it — shown
     *  under the remedy, never instead of it. */
    technical: string;
};

const OFFLINE: Omit<Remedy, "technical"> = {
    // `fetch` rejects rather than resolving when nothing is listening, so this
    // is the one failure that arrives with no status at all. It is also the
    // most common one in practice: the engine is a separate process, and a
    // process can die while its window stays open.
    headline: "Kriko's engine stopped answering",
    next:
        "The app and its engine are two processes, and the engine is the one "
        + "that went. Close the Kriko window and open it again — nothing is "
        + "lost; your history and packs are files on this machine.",
    retryable: true,
};

export function remedyFor(error: unknown): Remedy {
    const technical = error instanceof Error ? error.message : String(error);
    if (!(error instanceof ApiError)) {
        // A TypeError from `fetch`, or anything else that never reached the
        // server. Treated as offline rather than as a bug, because that is
        // what it is nine times in ten and the remedy is harmless if it is not.
        return { ...OFFLINE, technical };
    }
    if (error.status === 403) {
        return {
            headline: "The engine refused the request",
            next:
                "It only answers this window and the browser extension. If you "
                + "opened Kriko through some other address, use the app's own "
                + "window instead.",
            retryable: false,
            technical,
        };
    }
    if (error.status === 404) {
        return {
            headline: "That is not there any more",
            next:
                "A pack that was uninstalled, or a saved answer that was "
                + "cleared. Nothing to fix — go back and pick something that "
                + "still exists.",
            retryable: false,
            technical,
        };
    }
    if (error.status === 409) {
        return {
            headline: "Something else is already doing this",
            next:
                "One long job runs at a time on purpose. Wait for the one in "
                + "flight to finish, or cancel it.",
            retryable: true,
            route: "jobs",
            routeLabel: "Open Runs",
            technical,
        };
    }
    if (error.status === 422 || error.status === 400) {
        return {
            headline: "The engine could not use what it was given",
            next:
                "This is usually a listing it could read nothing from. Try "
                + "again with the page's own address, or paste the fields by "
                + "hand.",
            retryable: false,
            technical,
        };
    }
    if (error.status >= 500) {
        return {
            headline: "That is a bug in Kriko, not something you did",
            next:
                "The details below are the whole of it. Settings names the log "
                + "file this was also written to — send us that file and this "
                + "gets fixed.",
            retryable: true,
            route: "settings",
            routeLabel: "Where the log is",
            technical,
        };
    }
    return {
        headline: "The engine answered with a problem",
        next: "Trying again is safe. If it keeps happening, Settings names the log file.",
        retryable: true,
        route: "settings",
        routeLabel: "Where the log is",
        technical,
    };
}
