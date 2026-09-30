import type { ClaimHealth } from "./types";

const NOTE = {
    refuted: "a source in the pack contradicts this claim",
    thin: "only one independent source supports this",
    weak: "the best supporting source is a low-trust tier",
};

/** The one signal worth naming for this claim, worst first.
 *
 * Order matters and is not cosmetic: a contradicted claim is a different
 * problem from a thinly sourced one, and showing "only one source" on a claim
 * we hold a rebuttal to would bury the more serious signal.
 */
export function signalNote(claim: ClaimHealth): string {
    if (claim.refuted_by > 0) return NOTE.refuted;
    if (claim.independent_sources <= 1) return NOTE.thin;
    if (claim.best_trust < 0.5) return NOTE.weak;
    return "";
}

/** Warn when the worst claims are indistinguishable on every signal.
 *
 * Without this the reader takes the row order for a ranking. The list is the
 * worst N, not the whole ranking, and rows tied on all four signals are in
 * arbitrary order relative to each other.
 */
export function tieNote(claims: ClaimHealth[]): string {
    if (!claims.length) return "";
    const top = JSON.stringify(claims[0].concern);
    const tied = claims.filter((c) => JSON.stringify(c.concern) === top).length;
    if (tied < 2) return "";
    return (
        `${tied} of the claims shown tie on every signal: contradiction, ` +
        `independent sources, best-source trust and staleness alike, so their ` +
        `order relative to each other is arbitrary. This list is not the whole ` +
        `ranking, just the worst ${claims.length}.`
    );
}
