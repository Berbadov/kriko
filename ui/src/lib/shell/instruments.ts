import { writable } from "svelte/store";
import { api } from "../api";

/** The numbers the rail carries, and the reason it carries them at all.
 *
 * The rail used to be a list of places. A reader wanting to know whether
 * anything was running, how much this installation had spent, or whether the
 * packs actually held anything had to go and look — three navigations to
 * answer three questions that are each one integer.
 *
 * So the rail reads them. Three figures, on the rows they belong to, refreshed
 * on a slow clock.
 *
 * **Nothing here is a new endpoint.** `/api/status`, `/api/jobs` and
 * `/api/usage` are all already served and already polled by screens in this
 * app; this reads the same three and keeps the answers where every screen can
 * see them. A rail that needed its own endpoint would be a rail that goes
 * stale the day somebody changes what a claim is.
 */
export type Readings = {
    /** Claims across every enabled pack — what this installation *knows*. */
    claims: number | null;
    /** Jobs not yet finished. The one figure that changes while you watch. */
    running: number | null;
    /** Dollars, all research runs. `null` where nothing could be priced —
     *  which is not zero, and the rail must not draw it as zero. */
    spentUsd: number | null;
    /** Recent spend, oldest first, for the sparkline. Empty until two runs
     *  exist: one point is not a shape. */
    trail: number[];
    /** The last read failed. Kept rather than thrown: a rail that empties
     *  itself because one poll timed out reads as "you have nothing". */
    stale: boolean;
};

export const EMPTY: Readings = {
    claims: null,
    running: null,
    spentUsd: null,
    trail: [],
    stale: false,
};

/** How often the rail re-reads. Slow on purpose.
 *
 * These are ambient figures, not a progress bar — the screen that is actually
 * watching a job polls it at `jobs.POLL_MS` and always will. A rail that
 * refreshed at that rate would put three requests a second behind a reader who
 * is reading. Thirty seconds is "recent enough to trust", and a job starting
 * or finishing pushes its own update through `nudge()` without waiting.
 */
export const EVERY_MS = 30_000;

/** How many runs the sparkline shows. */
export const TRAIL = 12;

export const readings = writable<Readings>(EMPTY);

const num = (value: unknown): number | null =>
    typeof value === "number" && Number.isFinite(value) ? value : null;

/** Read all three, and let each fail on its own.
 *
 * `Promise.allSettled`, not `all`: a rail where one dead endpoint blanks the
 * other two figures is worse than a rail missing one. `stale` is set only when
 * *everything* failed, because that is the case where the reader should stop
 * believing what they see.
 */
export async function read(): Promise<Readings> {
    const [status, jobs, usage] = await Promise.allSettled([
        api.status(),
        api.jobs(TRAIL),
        api.usage(),
    ]);

    const claims =
        status.status === "fulfilled" ? num(status.value.counts?.claims) : null;
    const running =
        jobs.status === "fulfilled"
            ? jobs.value.items.filter((one) => !one.done).length
            : null;
    const spentUsd =
        usage.status === "fulfilled" ? num(usage.value.research?.spent_usd) : null;

    // The trail is per-plane spend, which is the only history the usage
    // endpoint holds. Not per-run: `/api/usage` totals runs rather than
    // listing them, and inventing a series from one total would be a drawn
    // line that means nothing.
    const planes =
        usage.status === "fulfilled" ? (usage.value.research?.planes ?? []) : [];
    const trail = planes
        .map((one) => num(one.spent_usd))
        .filter((one): one is number => one !== null);

    return {
        claims,
        running,
        spentUsd,
        trail: trail.length > 1 ? trail.slice(-TRAIL) : [],
        stale: [status, jobs, usage].every((one) => one.status === "rejected"),
    };
}

let timer: ReturnType<typeof setTimeout> | undefined;
let watching = false;

async function tick(): Promise<void> {
    if (!watching) return;
    try {
        const next = await read();
        if (watching) readings.set(next);
    } catch {
        // `read` settles everything itself; reaching here means the store
        // update threw, which is not worth stopping the clock over.
    }
    if (watching) timer = setTimeout(() => void tick(), EVERY_MS);
}

/** Start the clock. Idempotent — a second call does not start a second one. */
export function watch(): () => void {
    if (watching) return unwatch;
    watching = true;
    void tick();
    return unwatch;
}

export function unwatch(): void {
    watching = false;
    if (timer) clearTimeout(timer);
    timer = undefined;
}

/** Read now, without waiting for the clock.
 *
 * For the moment a job is submitted or cancelled: the reader pressed a thing
 * and the number beside it should move, rather than being right in half a
 * minute.
 */
export function nudge(): void {
    if (!watching) return;
    if (timer) clearTimeout(timer);
    void tick();
}
