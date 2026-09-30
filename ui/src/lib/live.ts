import type { FeedEvent, Job } from "./types";

/** What the dark panel says about a run, derived from the events the server
 * already classified (`app/web/livefeed.py`). Nothing here reads a log line. */

export type Tally = { sources: number; searches: number; findings: number; problems: number };

export function tally(feed: FeedEvent[] | undefined): Tally {
    const out: Tally = { sources: 0, searches: 0, findings: 0, problems: 0 };
    for (const event of feed ?? []) {
        if (event.kind === "source") out.sources += 1;
        else if (event.kind === "search") out.searches += 1;
        else if (event.kind === "finding") out.findings += 1;
        else if (event.kind === "problem") out.problems += 1;
    }
    return out;
}

/** What the agent is doing right now, in one line: the newest event, or the
 * job's own status message before it has done anything. */
export function doing(job: Job): string {
    const feed = job.feed ?? [];
    return feed[feed.length - 1]?.text || job.message || "Starting";
}

/** The agent a run used: the one it named, else the one the machine prefers,
 * else the first installed. All three are ids the API returned. */
export function agentOf(
    job: Job,
    preferred: string,
    installed: { id: string; label: string }[],
): { id: string; label: string } {
    const named = String(job.params?.harness ?? "") || preferred;
    return (
        installed.find((one) => one.id === named) ??
        installed[0] ?? { id: named, label: named || "Agent" }
    );
}
