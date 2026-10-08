/** Whether the reader asked for less motion. Read at the moment of use. Where
 * the platform cannot say (no `matchMedia`, as in some test environments) the
 * answer is `false`, so a missing query never freezes the interface. */
export function prefersReducedMotion(): boolean {
    try {
        return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    } catch {
        return false;
    }
}
