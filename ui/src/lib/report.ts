import type { Claim, LookupResult } from "./types";

/** Severity is one of the engine's few closed vocabularies (`rank.py`'s
 * SEVERITY_WEIGHT), so ordering on it here is not the hardcoded-pack-data bug
 * — a domain or a term id would be. */
const SEVERITY_RANK: Record<string, number> = { high: 0, medium: 1, low: 2 };

const SEVERITY_WORD: Record<string, string> = {
    high: "Serious",
    medium: "Worth checking",
    low: "Minor",
};

export const severityRank = (severity: string): number =>
    SEVERITY_RANK[severity] ?? 1.5;

export const severityWord = (severity: string): string =>
    SEVERITY_WORD[severity] ?? severity;

/** A stable per-claim identity for the reader's own notes.
 *
 * `/api/lookup` returns `claim_id`; `/api/analyze` does not, and a checkmark
 * has to survive on both. The fallback is pack-scoped so two packs asserting
 * the same title stay two separate rows to tick off.
 */
export const claimKey = (claim: Claim): string =>
    claim.claim_id || `${claim.pack_id}:${claim.title}`;

/** Urgency order, which is not the engine's order.
 *
 * The engine sorts by relevance first (`lookup/__init__.py`), because
 * relevance is what it is confident about. A reader deciding whether to walk
 * away from a purchase reads consequence first: every serious risk should be
 * above every minor one, however well the minor one scored.
 */
export const orderClaims = (claims: Claim[]): Claim[] =>
    [...claims].sort(
        (a, b) =>
            severityRank(a.severity) - severityRank(b.severity) ||
            (b.relevance ?? 0) - (a.relevance ?? 0) ||
            a.title.localeCompare(b.title),
    );

export type Group = { domain: string; claims: Claim[] };

/** Grouped by the pack's own domain, groups ordered by their worst claim.
 *
 * The domain strings come from the payload and are never enumerated here —
 * a pack invents its own systems, and this function must not know one.
 */
export function groupByDomain(claims: Claim[]): Group[] {
    const groups = new Map<string, Claim[]>();
    for (const claim of orderClaims(claims)) {
        const domain = claim.domain || "other";
        if (!groups.has(domain)) groups.set(domain, []);
        groups.get(domain)!.push(claim);
    }
    return [...groups.entries()]
        .map(([domain, grouped]) => ({ domain, claims: grouped }))
        .sort(
            (a, b) =>
                severityRank(a.claims[0].severity) -
                    severityRank(b.claims[0].severity) ||
                b.claims.length - a.claims.length ||
                a.domain.localeCompare(b.domain),
        );
}

/** What the sources amount to, in a sentence rather than a tier table. */
export function sourceSummary(claim: Claim): string {
    const sources = claim.sources ?? [];
    if (!sources.length) return "No source cited — this is a service-interval item.";
    const against = sources.filter((s) => s.stance === "refutes").length;
    const forCount = sources.length - against;
    const agree =
        forCount === 1 ? "1 source reports this" : `${forCount} sources report this`;
    return against ? `${agree}, ${against} disagrees` : agree;
}

/** Why this report is empty, which is two different situations.
 *
 * "We could not identify the thing" and "we identified it and know nothing
 * about it" lead the reader to opposite next steps, and a single "no results"
 * hides which one happened.
 */
export function emptyReason(result: LookupResult): string {
    if (result.coverage === "NOT_MATCHED" || result.method === "no_match") {
        return (
            "No installed pack recognised this one. Check the details, " +
            "or install a pack that covers it."
        );
    }
    return (
        "This one was identified, but the installed packs hold nothing " +
        "about it yet. That is a coverage gap, not a clean bill of health."
    );
}

/** The header line, in words rather than in enum values. */
export function confidenceNote(result: LookupResult): string {
    const exact = result.method === "exact" || result.method === "identity";
    const how = exact
        ? "Matched exactly on the details given"
        : `Matched by ${(result.method || "unknown").replace(/_/g, " ")}`;
    const covered =
        result.coverage && result.coverage !== "NOT_MATCHED"
            ? `, coverage ${result.coverage.toLowerCase().replace(/_/g, " ")}`
            : "";
    return `${how}${covered}.`;
}

export const askLine = (claim: Claim): string =>
    claim.advice?.trim() ||
    "Ask the seller for proof this has been dealt with, and have it checked.";
