import type { HistoryItem } from "./types";

/** One product checked one or more times: the newest check stands for all. */
export type HistoryEntry = {
    /** The newest check, which the card opens. */
    latest: HistoryItem;
    /** Every check of this product in this category, newest first. */
    checks: HistoryItem[];
};

export type HistoryGroup = {
    /** The pack's own name, or empty for checks no pack answered. */
    category: string;
    entries: HistoryEntry[];
    /** Checks in the group, repeats included, so a count matches what was run. */
    total: number;
};

/** Fold repeat checks of one product into one entry (B182).
 *
 * "Three identical MacBook rows" were one product checked three times. The
 * key is the label within a category: the same label under two categories is
 * two products. Input order is newest first, and entries keep the order of
 * their newest check.
 */
export function foldRepeats(items: HistoryItem[]): HistoryEntry[] {
    const byKey = new Map<string, HistoryEntry>();
    for (const item of items) {
        const key = `${item.category ?? ""}\u0000${item.label.trim().toLowerCase()}`;
        const found = byKey.get(key);
        if (found) found.checks.push(item);
        else byKey.set(key, { latest: item, checks: [item] });
    }
    return [...byKey.values()];
}

/** Group checks under the category their pack names, newest group first.
 *
 * The category is whatever the API row carries: nothing here names one. Groups
 * appear in the order of their newest check, and checks no pack answered come
 * last, because the reader's categories are the point of the screen.
 */
export function groupByCategory(items: HistoryItem[]): HistoryGroup[] {
    const groups = new Map<string, HistoryItem[]>();
    for (const item of items) {
        const key = item.category ?? "";
        groups.set(key, [...(groups.get(key) ?? []), item]);
    }
    const out = [...groups.entries()].map(([category, rows]) => ({
        category,
        entries: foldRepeats(rows),
        total: rows.length,
    }));
    return out.sort((a, b) => Number(a.category === "") - Number(b.category === ""));
}
