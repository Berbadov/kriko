import { claimKey, confidenceNote, emptyReason } from "./report";
import type { LookupResult } from "./types";

export type Counts = {
    total: number;
    high: number;
    medium: number;
    low: number;
    handled: number;
};

export type Verdict = {
    headline: string;
    counts: Counts;
    note: string;
    tone: "clear" | "caution" | "alarm" | "unknown";
};

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** The report's top line, derived from the payload and nothing else.
 *
 * Two rules this function exists to keep. It never states a clean bill of
 * health: an empty answer means the packs hold nothing, which is a coverage
 * gap, and saying "nothing wrong" would be a claim the engine never made. And
 * it never carries a repair cost — `Claim` has no price field, so any figure
 * here would be invented.
 */
export function verdictFor(result: LookupResult, handled: string[]): Verdict {
    const marked = new Set(handled);
    const counts: Counts = {
        total: result.claims.length,
        high: result.claims.filter((c) => c.severity === "high").length,
        medium: result.claims.filter((c) => c.severity === "medium").length,
        low: result.claims.filter((c) => c.severity === "low").length,
        handled: result.claims.filter((c) => marked.has(claimKey(c))).length,
    };

    if (!counts.total) {
        return {
            headline: "Nothing known about this one yet",
            counts,
            note: emptyReason(result),
            tone: "unknown",
        };
    }

    const tail = counts.handled ? ` · ${counts.handled} handled` : "";
    const headline = counts.high
        ? `${plural(counts.total, "known risk")}, ${counts.high} serious${tail}`
        : `${plural(counts.total, "known risk")}, none serious${tail}`;

    return {
        headline,
        counts,
        note: confidenceNote(result),
        tone: counts.high ? "alarm" : "caution",
    };
}

/** The distribution bar's segments, worst first. Percentages, not counts, so
 * the bar reads at a glance without a legend. */
export function severityShare(counts: Counts): { severity: string; percent: number }[] {
    if (!counts.total) return [];
    return (["high", "medium", "low"] as const)
        .map((severity) => ({
            severity,
            percent: Math.round((counts[severity] / counts.total) * 100),
        }))
        .filter((segment) => segment.percent > 0);
}
