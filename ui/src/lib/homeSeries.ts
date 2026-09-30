/** Day buckets for the Home graphs (B174).
 *
 * The server keeps rows, not time series, so the graphs are counted here from
 * `/api/operations` and `/api/jobs`. Days are the reader's own local days, and
 * a timestamp with no offset is UTC, the same rule `time.ts` applies. */
export type Day = { day: string; value: number };

const pad = (n: number) => String(n).padStart(2, "0");
const keyOf = (date: Date) =>
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;

const dayOf = (at: string | null | undefined): string | null => {
    if (!at) return null;
    const zoned = /[zZ]|[+-]\d\d:\d\d$/.test(at) ? at : `${at}Z`;
    const date = new Date(zoned);
    return Number.isNaN(date.getTime()) ? null : keyOf(date);
};

/** The last `count` local days, oldest first, ending on `now`'s day. */
export function dayKeys(count: number, now: Date = new Date()): string[] {
    return Array.from({ length: count }, (_, i) => {
        const date = new Date(now);
        date.setDate(date.getDate() - (count - 1 - i));
        return keyOf(date);
    });
}

function bucket(days: string[], add: (put: (at: string | null | undefined, n: number) => void) => void): Day[] {
    const sums = new Map(days.map((day) => [day, 0]));
    add((at, n) => {
        const day = dayOf(at);
        if (day !== null && sums.has(day)) sums.set(day, sums.get(day)! + n);
    });
    return days.map((day) => ({ day, value: sums.get(day)! }));
}

type Result = Record<string, unknown> | null | undefined;
type JobRow = { finished_at: string | null; result: Result };

/** Findings a finished job put in the store. Jobs report it as a list
 *  (`accepted`), a count (`accepted`) or `kept`, depending on the kind. */
const gained = (result: Result): number => {
    const accepted = result?.accepted;
    if (Array.isArray(accepted)) return accepted.length;
    if (typeof accepted === "number") return accepted;
    return typeof result?.kept === "number" ? result.kept : 0;
};

export const checksByDay = (
    rows: { kind: string; started_at: string }[],
    days: string[],
): Day[] =>
    bucket(days, (put) => rows.forEach((row) => row.kind === "lookup" && put(row.started_at, 1)));

export const knowledgeByDay = (jobs: JobRow[], days: string[]): Day[] =>
    bucket(days, (put) => jobs.forEach((job) => put(job.finished_at, gained(job.result))));

/** Null when no job in the window carried a counted cost: nothing measured is
 *  not a measured zero (the rule `Usage.svelte` states). */
export function spendByDay(jobs: JobRow[], days: string[]): Day[] | null {
    const counted = jobs.filter((job) => typeof job.result?.spent_usd === "number");
    if (!counted.length) return null;
    return bucket(days, (put) =>
        counted.forEach((job) => put(job.finished_at, job.result!.spent_usd as number)),
    );
}
