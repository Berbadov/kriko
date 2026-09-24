import { api } from "./api";
import type { Operation } from "./types";

/** How often the fallback asks for new rows. Matches the server's poll. */
export const POLL_MS = 1000;

/**
 * Follow the operations feed and return the way to stop.
 *
 * Every row this installation records, whichever door it came in by: a tool
 * call from the reader's own coding agent, a job the app started, an analysis
 * the extension asked for. `after` is an id rather than a timestamp, so a
 * reconnect resumes exactly where it stopped and cannot re-show or skip a row.
 *
 * Server-Sent Events with a polling fallback, for the reason `jobs.ts` has
 * one: a stream that opens and then dies behind a proxy would otherwise leave
 * the feed looking frozen, which is indistinguishable from an installation
 * doing nothing — the exact confusion this feed exists to end.
 */
export function followOperations(
    after: number,
    onRow: (row: Operation) => void,
    open: number[] = [],
): () => void {
    let stopped = false;
    let cursor = after;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let source: EventSource | undefined;
    /* The ids still believed to be open.
     *
     * A row is written twice — opened `running` before the work, closed after
     * it — and the close is an update to a row whose id is already behind the
     * cursor. Following ids alone therefore delivered every operation's
     * beginning and none of its ending, and the screen whose whole job is
     * "what is happening right now" showed finished work as running until the
     * reader reloaded. So the poll says what it is still waiting on.
     *
     * Only the fallback needs this: the stream keeps the same set server-side,
     * because a client listening over SSE has no way to ask for anything. */
    const watching = new Set<number>(open);

    const stop = () => {
        stopped = true;
        if (timer) clearTimeout(timer);
        source?.close();
    };

    const take = (row: Operation) => {
        cursor = Math.max(cursor, row.op_id);
        if (row.state === "running") watching.add(row.op_id);
        else watching.delete(row.op_id);
        onRow(row);
    };

    const poll = async () => {
        if (stopped) return;
        try {
            const page = await api.operations(200, cursor, [...watching]);
            for (const row of page.items) take(row);
        } catch {
            // An unreachable engine is not a reason to stop watching: the app
            // may be starting, or the sidecar may be restarting under it.
        }
        timer = setTimeout(poll, POLL_MS);
    };

    if (typeof EventSource === "undefined") {
        void poll();
        return stop;
    }

    source = new EventSource(`/api/operations/stream?after_id=${cursor}`);
    source.onmessage = (event) => take(JSON.parse(event.data) as Operation);
    source.onerror = () => {
        source?.close();
        source = undefined;
        if (!stopped) void poll();
    };
    return stop;
}

/** What the door is called in the reader's terms.
 *
 * "mcp" is the one that matters and the one nobody outside this project would
 * recognise: it is their own coding agent, talking to Kriko. */
export const DOOR_WORD: Record<string, string> = {
    mcp: "your agent",
    job: "this app",
    extension: "the browser extension",
    app: "this app",
    cli: "the command line",
};

export const doorWord = (door: string) => DOOR_WORD[door] ?? door;

export const STATE_WORD: Record<string, string> = {
    running: "running",
    ok: "done",
    failed: "failed",
};

export const stateWord = (state: string) => STATE_WORD[state] ?? state;

/** Whether the feed may offer to stop this one.
 *
 * A job belongs to the runner in this process and can be cancelled from the
 * screen watching it. An MCP call belongs to the process that made it — the
 * reader's own coding agent — and this installation has no way to reach into
 * it. B122 left that gap open on purpose and it stayed open because the feed
 * could not tell the two apart; `job_id` is how a row says which it is.
 */
export const stoppable = (row: Operation): boolean =>
    row.state === "running" && Boolean(row.job_id);

/** How long a still-running operation has been going, in milliseconds.
 *
 * `ms` is written when the row closes, so a running row has none — and a feed
 * that therefore showed nothing was at its least informative for exactly the
 * operations a reader is watching. Derived from the clock rather than stored,
 * because the alternative is writing to the row every second.
 *
 * `started_at` is the server's UTC stamp. It is parsed as UTC explicitly: the
 * column has no zone marker, and a browser left to guess reads it as local
 * time, and in this reader's time zone every running operation would then
 * appear to have started three hours in the future.
 */
export const since = (row: Operation, now: number = Date.now()): number | null => {
    const at = (row.started_at || "").trim();
    if (!at) return null;
    const utc = /[zZ]|[+-]\d\d:?\d\d$/.test(at) ? at : at.replace(" ", "T") + "Z";
    const began = Date.parse(utc);
    if (Number.isNaN(began)) return null;
    return Math.max(0, now - began);
};

/** Milliseconds, as something a person reads at a glance. */
export const took = (ms: number | null): string => {
    if (ms === null || ms === undefined) return "";
    if (ms < 1000) return `${ms} ms`;
    if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
    return `${Math.round(ms / 60_000)} min`;
};
