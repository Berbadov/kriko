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
