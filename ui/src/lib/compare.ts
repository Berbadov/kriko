import { claimKey, orderClaims, severityRank } from "./report";
import type { Claim, StoredLookup } from "./types";

export type ComparedRow = {
    key: string;
    title: string;
    left: Claim | null;
    right: Claim | null;
};

export type Comparison = {
    rows: ComparedRow[];
    shared: number;
    onlyLeft: number;
    onlyRight: number;
};

/** Two stored answers, aligned by claim identity.
 *
 * Entirely client-side over two answers the reader already has: there is no
 * compare endpoint, and adding one would put a two-listing product decision
 * into the engine, which knows nothing about listings.
 *
 * Alignment uses `claimKey`, so it works across `/api/lookup` (which returns
 * claim_id) and `/api/analyze` (which does not) — the same identity the
 * reader's own handled-checkmarks use, which is what makes a row mean the same
 * thing on both sides.
 */
export function compare(left: StoredLookup, right: StoredLookup): Comparison {
    const rows = new Map<string, ComparedRow>();

    const put = (claim: Claim, side: "left" | "right") => {
        const key = claimKey(claim);
        const row = rows.get(key) ?? { key, title: claim.title, left: null, right: null };
        row[side] = claim;
        rows.set(key, row);
    };

    for (const claim of left.response.claims) put(claim, "left");
    for (const claim of right.response.claims) put(claim, "right");

    // Worst first: the reason to put two listings side by side is to find the
    // difference that would change the decision, and that is a serious claim
    // one of them has.
    const worst = (row: ComparedRow) =>
        Math.min(
            row.left ? severityRank(row.left.severity) : 99,
            row.right ? severityRank(row.right.severity) : 99,
        );

    const ordered = [...rows.values()].sort(
        (a, b) => worst(a) - worst(b) || a.title.localeCompare(b.title),
    );

    return {
        rows: ordered,
        shared: ordered.filter((r) => r.left && r.right).length,
        onlyLeft: ordered.filter((r) => r.left && !r.right).length,
        onlyRight: ordered.filter((r) => !r.left && r.right).length,
    };
}

/** One side's claims in the report's own order — used to render a column when
 * the reader asks for the two answers whole rather than aligned. */
export const column = (stored: StoredLookup): Claim[] => orderClaims(stored.response.claims);
