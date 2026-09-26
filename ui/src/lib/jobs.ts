import { api } from "./api";
import { nudge } from "./shell/instruments";
import type { Job } from "./types";

/** How often the fallback re-reads a job. Matches the server's stream poll. */
export const POLL_MS = 700;

/**
 * Follow one job until it finishes, and return the way to stop watching.
 *
 * Server-Sent Events when the browser has them, plain polling when it does
 * not — and the fallback is not only for old browsers: an `EventSource` that
 * opens and then dies (a proxy that buffers, a dropped connection) would
 * otherwise leave a job looking frozen forever, so a failed stream falls back
 * rather than giving up. The row is the source of truth either way, which is
 * what makes falling back safe.
 *
 * Every screen that starts or watches a job goes through here, which is why
 * this is also where the rail's figures get told: `nudge()` on the first
 * event and again on the last one, so "a job started" and "a job finished"
 * reach the rail the moment this screen learns it rather than on the rail's
 * own 30s clock (B145 ops-7). Every other tick is left to that clock — a
 * `running` count does not need per-token precision, only to not stay wrong
 * for half a minute after a run ends.
 */
export function follow(jobId: string, onUpdate: (job: Job) => void): () => void {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let source: EventSource | undefined;
    let first = true;

    const stop = () => {
        stopped = true;
        if (timer) clearTimeout(timer);
        source?.close();
    };

    const relay = (job: Job) => {
        if (first || job.done) nudge();
        first = false;
        onUpdate(job);
    };

    const poll = async () => {
        if (stopped) return;
        try {
            const job = await api.job(jobId);
            relay(job);
            if (job.done) return stop();
        } catch {
            // A job that has been forgotten is not an error worth looping on.
            return stop();
        }
        timer = setTimeout(poll, POLL_MS);
    };

    if (typeof EventSource === "undefined") {
        void poll();
        return stop;
    }

    source = new EventSource(`/api/jobs/${encodeURIComponent(jobId)}/stream`);
    source.onmessage = (event) => {
        const job = JSON.parse(event.data) as Job;
        relay(job);
        if (job.done) stop();
    };
    source.onerror = () => {
        source?.close();
        source = undefined;
        if (!stopped) void poll();
    };
    return stop;
}

/** `queued`, `running` and `cancelling` are the states worth watching.
 *
 * Derived from `done` rather than listed, which is why gaining a fourth live
 * state cost this line nothing.
 */
export const isLive = (job: Job) => !job.done;
export const canCancel = (job: Job) => isLive(job) && job.state !== "cancelling";

export const STATE_WORD: Record<string, string> = {
    queued: "waiting its turn",
    running: "running",
    // Two words for what used to be one. A run that has been asked to stop is
    // still spending until its teardown finishes, and showing "cancelled"
    // through that window is the reader's own report — they pressed the button
    // and watched the tokens keep going.
    cancelling: "stopping…",
    succeeded: "done",
    failed: "failed",
    cancelled: "stopped",
    interrupted: "interrupted by a restart",
};

export const stateWord = (job: Job) => STATE_WORD[job.state] ?? job.state;
