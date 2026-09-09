/** Which row the rail's moving marker belongs on.
 *
 * This is a module rather than three lines inside the effect because the bug
 * it fixes was invisible in every test the app had, and a function taking a
 * DOM node is the only version of it jsdom can assert.
 *
 * **The bug.** The effect used to find its row with
 * `navEl.querySelector(".nav-link.active")`. That class is applied by
 * `NavGroup`, a *child* component. Svelte 5 flushes a parent's `$effect`
 * before its children's template updates, so the query ran against the
 * previous route's markup and measured the row the reader had just left. The
 * marker sat one navigation behind — a yellow bar beside History while Packs
 * was plainly the open screen.
 *
 * **The fix.** Stop asking the DOM which row is active and tell it. Every row
 * carries `data-route`, and the route is the thing we already have in hand, so
 * the lookup no longer depends on when a child re-rendered. There is nothing
 * left to be stale.
 *
 * The `.active` query stays as a fallback for exactly one case: a mode switch
 * removes whole groups, and for one frame the row for the new route may not
 * exist yet. Being one frame behind beats vanishing.
 */
export function rowFor(nav: HTMLElement, route: string): HTMLElement | null {
    return (
        nav.querySelector<HTMLElement>(`.nav-link[data-route="${route}"]`) ??
        nav.querySelector<HTMLElement>(".nav-link.active")
    );
}
