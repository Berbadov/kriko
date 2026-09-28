import { ApiError } from "./api";

/**
 * A job that ran and failed, as opposed to a request that never reached the
 * server. `remedyFor` treats every non-`ApiError` as the engine having gone
 * away (see `OFFLINE` below), which was right for a `fetch` rejection and
 * wrong for this: Welcome's "Install and get started" used to wrap a failed
 * job's own message in a plain `Error`, so a 404 from the pack index read as
 * "close the Kriko window and open it again" — advice that fixes nothing,
 * because the engine answered fine; the *download* is what failed (B145
 * settings-2). Anything that runs a job and shows its failure through
 * `Failure` should throw this instead of a bare `Error`.
 */
export class JobFailedError extends Error {
    constructor(message: string) {
        super(message);
        this.name = "JobFailedError";
    }
}

/**
 * A `.kpack` file the reader chose that the engine refused, as opposed to a
 * listing the extension could read nothing from. Both land as a plain 400
 * from `request()`, and `remedyFor`'s generic 400/422 branch is written for
 * the listing case ("paste the fields by hand") — read on Welcome's file
 * picker it told a reader whose file was simply the wrong shape to go paste
 * a listing's fields, which fixes nothing (B145 settings-16). Anything that
 * installs a file the reader picked should throw this instead of the bare
 * `ApiError`.
 */
export class PackInstallFailedError extends Error {
    /** The engine's own reason, without the status prefix `request()` adds. */
    constructor(refused: ApiError) {
        super(refused.message.replace(/^\d+: /, ""));
        this.name = "PackInstallFailedError";
    }
}

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
    if (error instanceof JobFailedError) {
        return {
            headline: "That didn't finish",
            next: technical || "Try again, or use a file instead.",
            retryable: true,
            technical,
        };
    }
    if (error instanceof PackInstallFailedError) {
        return {
            headline: "That file isn't a pack Kriko can install",
            next:
                technical
                    || "Choose a different .kpack file, or install one from the "
                        + "index above instead.",
            // Retrying installs the exact same file again, which fails the
            // exact same way — the remedy is a different file, not another
            // attempt at this one (B145 settings-17).
            retryable: false,
            technical,
        };
    }
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
        // `technical` is always "<status>: <message>" (`ApiError`'s own
        // constructor), so the field name a pydantic validation error left
        // in `<message>` is everything after that fixed prefix. A pydantic
        // error is rendered "field: reason" by `api.ts`'s `explain` — a
        // second ": " past the prefix means it names an actual field and
        // bound, which is a better remedy than the generic listing copy
        // below and is what a bench/pack-author 422 (a source count over the
        // route's own limit, a category too short) actually is.
        const body = technical.replace(/^\d+: /, "");
        const named = /^[a-zA-Z_.\[\]0-9]+: /.test(body);
        return {
            headline: named
                ? "One of the values isn't allowed"
                : "The engine could not use what it was given",
            next: named
                ? body
                : "This is usually a listing it could read nothing from. Try "
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
