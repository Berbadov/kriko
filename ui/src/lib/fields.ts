/** A form value as the API should receive it.
 *
 * Identity and context values are typed by the pack, not by us: a pack may
 * declare a text attribute whose values happen to look numeric, and a context
 * key that is genuinely a number. Coercing a numeric-looking string is the
 * right default; the important part is that an empty field stays empty rather
 * than becoming 0.
 */
export const coerce = (value: string): string | number => {
    const trimmed = (value ?? "").trim();
    if (!trimmed) return "";
    const asNumber = Number(trimmed);
    return Number.isNaN(asNumber) ? trimmed : asNumber;
};

export const collect = (
    entries: Record<string, string>,
): Record<string, string | number> =>
    Object.fromEntries(
        Object.entries(entries)
            .map(([key, value]) => [key, coerce(value)] as const)
            .filter(([, value]) => value !== ""),
    );

/** A pack's key, spelled for a reader.
 *
 * Deliberately a string transform and not a lookup table. A table of
 * key → friendly label would be pack vocabulary living in the frontend —
 * the thing `test_ui_contains_no_pack_vocabulary` exists to catch, and the
 * thing that goes stale the first time a pack adds a key. This reads whatever
 * the API hands it, including keys from a category nobody has written yet.
 */
export const humanize = (key: string): string => {
    const words = (key ?? "").replace(/[_-]+/g, " ").trim();
    if (!words) return "";
    return words.charAt(0).toUpperCase() + words.slice(1);
};

/** A context term's label, with its own unit shown once (check-24).
 *
 * A term id like `usage_km` already spells its unit, because that is how the
 * pack names the thing — and the form separately renders `term.unit` next to
 * it, which read "Usage km km". Still a string transform, not a lookup table
 * (see `humanize`'s note): this only drops a trailing `_<unit>` when the term
 * id actually ends with the unit the pack declared, so a term with no such
 * suffix (or a unit that means something else) is untouched.
 */
export const contextLabel = (termId: string, unit: string): string => {
    const suffix = unit ? `_${unit.toLowerCase()}` : "";
    const bare = suffix && termId.toLowerCase().endsWith(suffix)
        ? termId.slice(0, termId.length - suffix.length)
        : termId;
    return humanize(bare);
};
