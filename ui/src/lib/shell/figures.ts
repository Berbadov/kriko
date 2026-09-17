import type { Readings } from "./instruments";

/** Which rail rows carry a number, and what it says.
 *
 * Separated from the components because *which* number belongs on *which* row
 * is the decision worth testing, and testing it through a rendered rail means
 * testing it through three layers of markup that are not the point.
 *
 * Three rows carry one, and the rest carry none deliberately. A figure on
 * every row is a dashboard, and a dashboard in a rail is a rail nobody can
 * scan — the number has to be rare enough that its presence means something.
 */
export type Figure = {
    /** What is drawn. Already formatted; the rail does no arithmetic. */
    text: string;
    /** The accessible name, which says what the number *is*. "162" alone is
     *  not a fact, and a screen reader announcing "Browse, 162" is noise. */
    title: string;
    /** Draw it as live rather than ambient — running work, not a total. */
    live?: boolean;
    /** The series for a sparkline beside it, if it has one. */
    trail?: number[];
};

/** Thousands separated, because five digits unseparated is a password. */
export const count = (value: number): string => value.toLocaleString("en-GB");

/** Dollars, at the precision the number deserves.
 *
 * Under ten dollars the cents are the story — a run that cost $0.34 and one
 * that cost $0.02 are a different decision — and above it they are noise on a
 * rail that has 40 pixels for this.
 */
export const money = (value: number): string =>
    value >= 10 ? `$${Math.round(value)}` : `$${value.toFixed(2)}`;

export function figures(readings: Readings): Record<string, Figure> {
    const out: Record<string, Figure> = {};

    // What the packs hold. Zero is worth drawing here, unlike everywhere else
    // below: an installation with no claims is the single most useful thing
    // this rail can tell a reader, and it is the state a fresh install is in.
    if (readings.claims !== null) {
        out.knowledge = {
            text: count(readings.claims),
            title: `${count(readings.claims)} claims across the installed packs`,
        };
    }

    // Only when something is running. A steady "0" beside Activity trains the
    // reader to stop looking at it, which costs the one moment it matters.
    if (readings.running) {
        out.activity = {
            text: count(readings.running),
            title:
                readings.running === 1
                    ? "1 job running"
                    : `${count(readings.running)} jobs running`,
            live: true,
        };
    }

    // Spend. `null` is not zero and must not be drawn as it — a plane with no
    // price row still meters its tokens and reports no cost, and a rail saying
    // "$0.00" over a run that cost real money is the error that compounds.
    if (readings.spentUsd !== null) {
        out.agents = {
            text: money(readings.spentUsd),
            title: `${money(readings.spentUsd)} spent on research so far`,
            trail: readings.trail.length > 1 ? readings.trail : undefined,
        };
    }

    return out;
}
