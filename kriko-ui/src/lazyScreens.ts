import { lazy } from 'react'
import { whenIdle } from './idle'
import { prefetchMarkdown } from './ui/Markdown'
import type { Screen } from './ui/drawerEvents'

/**
 * Every screen except Ask is its own chunk, so the first paint ships what the
 * Ask landing needs and nothing else. `prefetchScreen` warms one chunk (the
 * rail calls it on hover and focus) and `prefetchAll` warms the rest when the
 * window is idle after the first paint, so a move down the rail never waits on
 * the network or the disk. `import()` is cached by the module system, so asking
 * twice costs nothing.
 */
const loaders = {
  compare: () => import('./screens/Compare'),
  checklist: () => import('./screens/CheckList'),
  estimate: () => import('./screens/Estimate'),
  prices: () => import('./screens/Prices'),
  product: () => import('./screens/Product'),
  queue: () => import('./screens/Queue'),
  settings: () => import('./screens/Settings'),
  history: () => Promise.all([import('./ui/panels/History'), import('./ui/ChatsList')]),
  foryou: () => import('./ui/panels/ForYou'),
  catalogs: () => import('./ui/panels/Catalogs'),
  sites: () => import('./ui/panels/Sites'),
  tour: () => import('./tour/Tour'),
  palette: () => import('./ui/CommandPalette'),
}

export const CompareScreen = lazy(() => loaders.compare().then((one) => ({ default: one.CompareScreen })))
export const CheckListScreen = lazy(() => loaders.checklist().then((one) => ({ default: one.CheckListScreen })))
export const EstimateScreen = lazy(() => loaders.estimate().then((one) => ({ default: one.EstimateScreen })))
export const PricesScreen = lazy(() => loaders.prices().then((one) => ({ default: one.PricesScreen })))
export const ProductScreen = lazy(() => loaders.product().then((one) => ({ default: one.ProductScreen })))
export const QueueScreen = lazy(() => loaders.queue().then((one) => ({ default: one.QueueScreen })))
export const SettingsScreen = lazy(() => loaders.settings().then((one) => ({ default: one.SettingsScreen })))
export const HistoryPanel = lazy(() => import('./ui/panels/History').then((one) => ({ default: one.HistoryPanel })))
export const ChatsList = lazy(() => import('./ui/ChatsList').then((one) => ({ default: one.ChatsList })))
export const ForYouPanel = lazy(() => loaders.foryou().then((one) => ({ default: one.ForYouPanel })))
export const CatalogsPanel = lazy(() => loaders.catalogs().then((one) => ({ default: one.CatalogsPanel })))
export const SitesPanel = lazy(() => loaders.sites().then((one) => ({ default: one.SitesPanel })))
export const CommandPalette = lazy(() => loaders.palette().then((one) => ({ default: one.CommandPalette })))
export const Tour = lazy(() => loaders.tour().then((one) => ({ default: one.Tour })))

const warm = (key: keyof typeof loaders) => {
  // A failed prefetch is not an error: the screen asks again when it is opened.
  void loaders[key]().catch(() => undefined)
}

/** Warm the chunk a screen needs. */
export function prefetchScreen(screen: Screen) {
  if (screen === 'chat') return
  warm(screen)
}

const SCREENS = ['compare', 'checklist', 'queue', 'history', 'estimate', 'prices', 'catalogs', 'settings', 'sites', 'foryou', 'product'] as const

/** Warm every screen, one at a time, each in its own idle slice, so the work
 *  never lands as one long task. Stops when `cancelled` says so. */
export function prefetchAll(cancelled: () => boolean = () => false) {
  const queue: (() => void)[] = [prefetchMarkdown, ...SCREENS.map((key) => () => warm(key))]
  const next = () => {
    const step = queue.shift()
    if (!step || cancelled()) return
    step()
    whenIdle(next, 1500)
  }
  next()
}
