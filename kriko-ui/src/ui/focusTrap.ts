/** Keep keyboard focus inside an open modal panel. Inert or visually absent
 *  controls are skipped; with no controls, the dialog itself keeps focus. */
export function keepTabInside(event: KeyboardEvent, panel: HTMLElement): void {
  if (event.key !== 'Tab') return
  const focusable = Array.from(
    panel.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((element) => !element.closest('[inert]') && element.getClientRects().length > 0)
  if (!focusable.length) {
    event.preventDefault()
    panel.focus()
    return
  }
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  const active = document.activeElement
  if (event.shiftKey && (active === first || active === panel || !panel.contains(active))) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (active === last || !panel.contains(active))) {
    event.preventDefault()
    first.focus()
  }
}
