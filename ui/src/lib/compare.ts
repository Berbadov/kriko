import { claimKey, orderClaims, severityRank } from "./report";
import type { Claim, StoredLookup } from "./types";

/** One risk, and what each answer being compared says about it.
 *
 * `cells` is positional and always as long as the list of answers, including
 * the nulls: a table cannot render "missing on the third" from a sparse map,
 * and a shorter row would silently shift every column after the gap.
 */
export type ComparedRow = {
    key: string;
    title: string;
    cells: (Claim | null)[];
};

export type Comparison = {
    rows: ComparedRow[];
    /** Present in every answer. */
    shared: number;
    /** Present in exactly one — per side, in the same order as the inputs. */
    only: number[];
};

/** Any number of stored answers, aligned by claim identity.
 *
 * Two was the shape of the first version and the wrong shape for the job:
 * shopping means a shortlist, and being able to line up only two of the three
 * cars someone is weighing turned the screen into a thing they used once.
 *
 * Entirely client-side over answers the reader already has: there is no
 * compare endpoint, and adding one would put a multi-listing product decision
 * into the engine, which knows nothing about listings.
 *
 * Alignment uses `claimKey`, so it works across `/api/lookup` (which returns
 * claim_id) and `/api/analyze` (which does not) — the same identity the
 * reader's own handled-checkmarks use, which is what makes a row mean the same
 * thing on every side.
 */
export function compareMany(answers: StoredLookup[]): Comparison {
    const width = answers.length;
    const rows = new Map<string, ComparedRow>();

    answers.forEach((answer, side) => {
        for (const claim of answer.response.claims) {
            const key = claimKey(claim);
            const row =
                rows.get(key) ??
                { key, title: claim.title, cells: Array(width).fill(null) };
            row.cells[side] = claim;
            rows.set(key, row);
        }
    });

    // Worst first: the reason to put listings side by side is to find the
    // difference that would change the decision, and that is a serious claim
    // one of them has.
    const worst = (row: ComparedRow) =>
        Math.min(
            ...row.cells.map((cell) => (cell ? severityRank(cell.severity) : 99)),
        );

    const ordered = [...rows.values()].sort(
        (a, b) => worst(a) - worst(b) || a.title.localeCompare(b.title),
    );

    const present = (row: ComparedRow) => row.cells.filter(Boolean).length;

    return {
        rows: ordered,
        shared: width ? ordered.filter((row) => present(row) === width).length : 0,
        only: answers.map(
            (_, side) =>
                ordered.filter((row) => present(row) === 1 && row.cells[side]).length,
        ),
    };
}

/** One side's claims in the report's own order — used to render a column when
 * the reader asks for the answers whole rather than aligned. */
export const column = (stored: StoredLookup): Claim[] =>
    orderClaims(stored.response.claims);
