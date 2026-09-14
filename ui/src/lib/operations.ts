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
): () => void {
    let stopped = false;
    let cursor = after;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let source: EventSource | undefined;

    const stop = () => {
        stopped = true;
        if (timer) clearTimeout(timer);
        source?.close();
    };

    const take = (row: Operation) => {
        cursor = Math.max(cursor, row.op_id);
        onRow(row);
    };

    const poll = async () => {
        if (stopped) return;
        try {
            const page = await api.operations(200, cursor);
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

/** Milliseconds, as something a person reads at a glance. */
export const took = (ms: number | null): string => {
    if (ms === null || ms === undefined) return "";
    if (ms < 1000) return `${ms} ms`;
    if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
    return `${Math.round(ms / 60_000)} min`;
};
