import { writable } from "svelte/store";
import { api } from "./api";

/** Which palette the app wears.
 *
 * A theme is one complete set of colour aliases in `styles/themes/<id>.css`,
 * selected by `data-theme` on the root element. Adding one is two steps —
 * a stylesheet and a line in `THEMES` — and `styles/tokens.test.ts` refuses a
 * theme that defines only part of the set.
 *
 * The choice rides the free-form settings table, which is why this file needs
 * no backend change at all: `/api/settings` was deliberately built to hold
 * "whatever the interface wants remembered".
 */
export type Theme = "slate" | "lemonade";

export const THEMES: Theme[] = ["slate", "lemonade"];
export const DEFAULT_THEME: Theme = "slate";

export const THEME_LABELS: Record<Theme, string> = {
    slate: "Slate — follows your system",
    lemonade: "Lemonade — the extension's palette",
};

export const asTheme = (value: unknown): Theme =>
    THEMES.includes(value as Theme) ? (value as Theme) : DEFAULT_THEME;

export const theme = writable<Theme>(DEFAULT_THEME);

/** Set the attribute the stylesheets key off.
 *
 * Always written, even for the default: slate answers to both `[data-theme]`
 * and no attribute, and being explicit means the switch has a visible effect in
 * the DOM that a test can read.
 */
export function applyTheme(next: Theme): void {
    document.documentElement.dataset.theme = next;
    theme.set(next);
}

export async function initTheme(): Promise<Theme> {
    let stored = DEFAULT_THEME;
    try {
        stored = asTheme((await api.settings()).theme);
    } catch {
        // An engine we cannot reach is a reason to look plain, never a reason
        // to look unpainted.
    }
    applyTheme(stored);
    return stored;
}

export function setTheme(next: Theme): void {
    applyTheme(next);
    // Fire and forget, in that order: the reader sees the switch land whether
    // or not it is ever written down.
    void api.putSettings({ theme: next }).catch(() => {});
}
