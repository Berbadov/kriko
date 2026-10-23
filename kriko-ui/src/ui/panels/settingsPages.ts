/** The pages of the settings drawer, in the order the reader meets them. One
 *  page is shown at a time, so a page holds one job: looks, research, keys,
 *  connections, or usage and about. */
export const SETTINGS_PAGES = [
  { value: 'look', label: 'Look' },
  { value: 'research', label: 'Research' },
  { value: 'keys', label: 'Keys' },
  { value: 'connections', label: 'Connections' },
  { value: 'usage', label: 'Usage' },
] as const

export type SettingsPage = (typeof SETTINGS_PAGES)[number]['value']

const PAGE_EVENT = 'kriko:settings-page'

/** A page asked for before the drawer has mounted its panel, so the tour can
 *  open a step's target even when the reader last left the drawer elsewhere. */
let requested: SettingsPage | null = null

/** The tour asks for a page; a panel already open moves to it at once. */
export function showSettingsPage(page: SettingsPage) {
  requested = page
  window.dispatchEvent(new CustomEvent<SettingsPage>(PAGE_EVENT, { detail: page }))
}

/** The page asked for last, once. A panel that mounts with none asked opens Look. */
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
