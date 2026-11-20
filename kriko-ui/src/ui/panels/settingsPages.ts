/** The sections of the Settings screen, in the order the reader meets them in
 *  the list. One section is open at a time, and each holds one job: general
 *  looks and findings, research, keys and models, connections, usage and spend,
 *  and data with updates. */
export const SETTINGS_PAGES = [
  { value: 'general', label: 'General' },
  { value: 'research', label: 'Research' },
  { value: 'keys', label: 'Keys and models' },
  { value: 'connections', label: 'Connections' },
  { value: 'usage', label: 'Usage and spend' },
  { value: 'data', label: 'Data and updates' },
] as const

export type SettingsPage = (typeof SETTINGS_PAGES)[number]['value']

const PAGE_EVENT = 'kriko:settings-page'

/** A page asked for before the screen has mounted, so the tour can open a
 *  step's target even when the reader last left Settings elsewhere. */
let requested: SettingsPage | null = null

/** The tour asks for a page; a screen already open moves to it at once. */
export function showSettingsPage(page: SettingsPage) {
  requested = page
  window.dispatchEvent(new CustomEvent<SettingsPage>(PAGE_EVENT, { detail: page }))
}

/** The page asked for last, once. A screen that mounts with none asked opens General. */
export function takeRequestedSettingsPage(): SettingsPage | null {
  const page = requested
  requested = null
  return page
}

/** Subscribe to `showSettingsPage` while mounted. Returns the unsubscribe. */
export function onSettingsPage(listener: (page: SettingsPage) => void): () => void {
  const handle = (event: Event) => listener((event as CustomEvent<SettingsPage>).detail)
  window.addEventListener(PAGE_EVENT, handle)
  return () => window.removeEventListener(PAGE_EVENT, handle)
}

/** Whether a string names a section, for a route or a prop that arrives as text. */
export function isSettingsPage(value: unknown): value is SettingsPage {
  return SETTINGS_PAGES.some((page) => page.value === value)
}
