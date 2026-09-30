import type { Scale } from "./types";

/** What reading `count` sources is likely to cost, from what the server has
 * measured (B175).
 *
 * `/api/scales` measures a cost for each preset that has been run here. The
 * slider moves through counts no preset names, so the estimate is the
 * measured per-source rate times the count, taken from the preset nearest to
 * the chosen count. `null` where nothing has been measured: "no estimate" is
 * a different answer from zero, and the screen says which.
 */
export function estimateFor(scales: Scale[], count: number): number | null {
    const measured = scales.filter(
        (one) => one.usd !== null && one.usd !== undefined && one.max_documents > 0,
    );
    if (!measured.length || count <= 0) return null;
    const nearest = measured.reduce((best, one) =>
        Math.abs(one.max_documents - count) < Math.abs(best.max_documents - count) ? one : best,
    );
    return ((nearest.usd as number) / nearest.max_documents) * count;
}

/** The count a slider starts at: the server's default preset, else the first
 * preset that names a count, else a small fixed fallback. */
export function startingCount(scales: Scale[], preferred: string): number {
    const named = scales.find((one) => one.id === preferred && one.max_documents > 0);
    return named?.max_documents ?? scales.find((one) => one.max_documents > 0)?.max_documents ?? 7;
}
