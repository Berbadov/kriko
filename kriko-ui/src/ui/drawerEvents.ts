/** Every top-level screen the window can show. */
export type Screen = 'chat' | 'compare' | 'prices' | 'estimate' | 'queue' | 'history' | 'foryou' | 'catalogs' | 'sites' | 'settings'

/** The places Ctrl+1 to Ctrl+4 reach, in that order. Ctrl+, opens Settings. */
export const ORDER: Screen[] = ['chat', 'compare', 'prices', 'estimate']

/** The rail, top to bottom, then Settings. A move down the rail enters from below. */
export const RAIL_ORDER: Screen[] = ['chat', 'compare', 'queue', 'history', 'estimate', 'prices', 'catalogs', 'sites', 'foryou', 'settings']

/** Asks the shell to show a place. The name is kept from when these places
 *  opened in a drawer; the shell now navigates to a screen instead. */
export const DRAWER_EVENT = 'kriko:drawer'
export const showDrawer = (panel: string | null) => window.dispatchEvent(new CustomEvent<{ panel: string | null }>(DRAWER_EVENT, { detail: { panel } }))

/** Where each place asked for by name lands. The old settings-like panels are
 *  sections of the one Settings screen; `section` is the section's id. */
const ROUTES: Record<string, { screen: Screen; section?: string }> = {
  history: { screen: 'history' },
  foryou: { screen: 'foryou' },
  browse: { screen: 'catalogs' },
  sites: { screen: 'sites' },
  settings: { screen: 'settings', section: 'general' },
  agents: { screen: 'settings', section: 'research' },
  chat: { screen: 'settings', section: 'research' },
  local: { screen: 'settings', section: 'local' },
  setup: { screen: 'settings', section: 'connections' },
  logs: { screen: 'settings', section: 'data' },
  backups: { screen: 'settings', section: 'data' },
  updates: { screen: 'settings', section: 'data' },
  report: { screen: 'settings', section: 'data' },
}

/** The screen (and Settings section) a named place opens. `null` for no place,
 *  and for a name the shell does not know. */
export function routeFor(panel: string | null): { screen: Screen; section?: string } | null {
  if (panel === null || !Object.prototype.hasOwnProperty.call(ROUTES, panel)) return null
  const route = ROUTES[panel]
  return { ...route }
}
