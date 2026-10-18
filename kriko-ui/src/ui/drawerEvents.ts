/** The tour opens a drawer panel to point at something in it, then closes it.
 *  Nothing else uses this. `null` closes the drawer. */
export const DRAWER_EVENT = 'kriko:drawer'
export const showDrawer = (panel: string | null) => window.dispatchEvent(new CustomEvent<{ panel: string | null }>(DRAWER_EVENT, { detail: { panel } }))
