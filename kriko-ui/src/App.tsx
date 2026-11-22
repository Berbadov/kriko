import { Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, MotionConfig, motion } from 'motion/react'
import { usePrefs } from './prefs'
import { ChatProvider, useChatActions } from './chat'
import { CompareProvider, useCompareAdd } from './compare'
import { useAttention } from './engine/buyer'
import { useEngine } from './engine/Engine'
import { post } from './engine/api'
import { useHandoff, type Landing } from './handoff'
import { QueueProvider, useQueueActive } from './queue'
import { useAfterIdle, whenIdle } from './idle'
import { openCommandPalette } from './ui/paletteItems'
import { rememberEstimate, rememberNewEstimate } from './engine/pendingOpen'
import type { AppAction } from './activity/run'
import { ChatScreen } from './screens/Chat'
import { Motes } from './dust/Motes'
import { PixelSprites } from './ui/ProductGlyph'
import { DRAWER_EVENT, ORDER, RAIL_ORDER, routeFor, showDrawer, type Screen } from './ui/drawerEvents'
import { Rail, TopStrip } from './ui/Rail'
import { PanelPage } from './ui/PanelPage'
import { PageSkeleton } from './ui/PageSkeleton'
import {
  CatalogsPanel,
  ChatsList,
  CheckListScreen,
  CommandPalette,
  CompareScreen,
  EstimateScreen,
  ForYouPanel,
  HistoryPanel,
  PricesScreen,
  ProductScreen,
  QueueScreen,
  SettingsScreen,
  SitesPanel,
  Tour,
  prefetchAll,
  prefetchScreen,
} from './lazyScreens'

/** Named places the agent or a link can ask for, by the screen they are. */
const TARGETS: Record<string, Screen> = {
  chat: 'chat',
  compare: 'compare',
  checklist: 'checklist',
  prices: 'prices',
  estimate: 'estimate',
  queue: 'queue',
  history: 'history',
  catalogs: 'catalogs',
  'for-you': 'foryou',
  foryou: 'foryou',
  sites: 'sites',
  settings: 'settings',
}

/** The rail's entries by their title, for the prefetch on hover and focus. */
const RAIL_TITLES: Record<string, Screen> = {
  Compare: 'compare',
  'Check a list': 'checklist',
  Queue: 'queue',
  History: 'history',
  Procurement: 'estimate',
  Prices: 'prices',
  Catalogs: 'catalogs',
  Sites: 'sites',
  'For you': 'foryou',
  Settings: 'settings',
}

interface Nav {
  screen: Screen
  /** Which way the page moves in, for the slide: 1 from the right, -1 from the left. */
  direction: number
  product: string | null
  /** The Settings section to open, when the move named one. */
  section: string | null
  /** Counts the moves, so Settings opens its section again when asked while already there. */
  seq: number
}

function Shell() {
  const { motion: m } = usePrefs()
  const engine = useEngine()
  // Only what the shell shows is read from the providers: the queue's count, the
  // board's `add` and the chat's `newChat`. Their progress, answers and streamed
  // words change many times a second and are not the shell's business.
  const active = useQueueActive()
  const add = useCompareAdd()
  const attention = useAttention()
  const { newChat } = useChatActions()
  const pageRef = useRef<HTMLDivElement>(null)
  const tourReady = useAfterIdle(3000)
  const [nav, setNav] = useState<Nav>({ screen: 'chat', direction: 1, product: null, section: null, seq: 0 })
  const { screen, direction, product, section, seq } = nav
  /** One line about a started app action, until the reader dismisses it. */
  const [notice, setNotice] = useState('')

  // A move down the rail enters from below; a move up enters from above.
  const go = useCallback((next: Screen, toSection?: string) => {
    setNav((current) => ({
      screen: next,
      direction: RAIL_ORDER.indexOf(next) >= RAIL_ORDER.indexOf(current.screen) ? 1 : -1,
      product: null,
      section: next === 'settings' ? (toSection ?? null) : null,
      seq: current.seq + 1,
    }))
  }, [])

  const openProduct = useCallback((lookupId: string) => {
    setNav((current) => ({ screen: 'chat', direction: current.screen === 'chat' ? 1 : -1, product: lookupId, section: null, seq: current.seq + 1 }))
  }, [])

  // A place asked for by name (the tour, a link, an engine notice) navigates.
  useEffect(() => {
    const onPlace = (event: Event) => {
      const panel = (event as CustomEvent<{ panel: string | null }>).detail.panel
      const route = routeFor(panel)
      if (route) go(route.screen, route.section)
    }
    window.addEventListener(DRAWER_EVENT, onPlace)
    return () => window.removeEventListener(DRAWER_EVENT, onPlace)
  }, [go])

  // A screen asks to go somewhere else (an "Open it" after adding to an estimate).
  useEffect(() => {
    const onNavigate = (event: Event) => {
      const target = (event as CustomEvent<{ screen?: Screen }>).detail?.screen
      if (target && RAIL_ORDER.includes(target)) go(target)
    }
    window.addEventListener('kriko:navigate', onNavigate)
    return () => window.removeEventListener('kriko:navigate', onNavigate)
  }, [go])

  /** A named action the agent proposed. Navigation is the window's; a Quick
   *  Look is the engine's job and starts only after this press. */
  const performAction = useCallback((action: AppAction) => {
    if (action.kind === 'open') {
      const target = String(action.params?.screen || '')
      if (target in TARGETS) go(TARGETS[target])
      else if (target) showDrawer(target)
      return
    }
    if (action.kind === 'start_quick_look') {
      setNotice('Starting the Quick Look…')
      void post<{ job_id: string }>('/api/agent-actions', {
        name: 'start_quick_look',
        arguments: action.params,
      }).then((started) => {
        setNotice(`Quick Look started. Job ${started.job_id.slice(0, 8)} will appear in History when it finishes.`)
      }).catch((error: unknown) => {
        setNotice(error instanceof Error ? error.message : 'The Quick Look could not be started.')
      })
    }
  }, [go])

  // The extension hands a product over.
  const land = useCallback(
    (landing: Landing) => {
      if (landing.board) add(landing.board)
      if (landing.product) openProduct(landing.product)
      else go(landing.screen)
    },
    [add, go, openProduct],
  )
  useHandoff(land)

  /**
   * The shortcuts a desktop window is expected to have: Ctrl+1 to Ctrl+4 reach the
   * four places in `ORDER`, Ctrl+, opens Settings and Ctrl+K puts the cursor in
   * the composer. Escape is left to whatever has focus, so a global handler never
   * swallows it.
   */
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return
      const digit = ['1', '2', '3', '4'].indexOf(event.key)
      if (digit >= 0 && digit < ORDER.length) {
        event.preventDefault()
        go(ORDER[digit])
        return
      }
      if (event.key === ',') {
        event.preventDefault()
        go('settings')
        return
      }
      if (event.key.toLowerCase() === 'k') {
        event.preventDefault()
        if (screen !== 'chat') go('chat')
        // After the page has swapped, so the field exists to be focused.
        window.setTimeout(() => document.querySelector<HTMLTextAreaElement>('.composer-field')?.focus(), 0)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [go, screen])

  // Every other screen is its own chunk. Once the first paint is done and the window
  // is idle they are fetched one by one, so a move down the rail never waits.
  useEffect(() => {
    let cancelled = false
    const cancel = whenIdle(() => prefetchAll(() => cancelled), 2500)
    return () => {
      cancelled = true
      cancel()
    }
  }, [])

  /** Hovering or focusing a rail entry warms its chunk a moment before the press. */
  const warm = useCallback((event: { target: EventTarget }) => {
    const target = event.target instanceof Element ? event.target.closest<HTMLElement>('.lrail-item') : null
    const place = target ? RAIL_TITLES[target.title] : undefined
    if (place) prefetchScreen(place)
  }, [])

  const startChat = useCallback(() => {
    newChat()
    go('chat')
  }, [newChat, go])

  // The command palette is its own chunk. It is fetched when the window is idle,
  // or the first time its shortcut is pressed, and opens as soon as it is there.
  const [paletteReady, setPaletteReady] = useState(false)
  const openWhenReady = useRef(false)
  useEffect(() => {
    const cancel = whenIdle(() => setPaletteReady(true), 3000)
    const onKey = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || !event.shiftKey || event.key.toLowerCase() !== 'p') return
      if (paletteReady) return
      event.preventDefault()
      openWhenReady.current = true
      setPaletteReady(true)
    }
    window.addEventListener('keydown', onKey)
    return () => {
      cancel()
      window.removeEventListener('keydown', onKey)
    }
  }, [paletteReady])
  useEffect(() => {
    if (!paletteReady || !openWhenReady.current) return
    openWhenReady.current = false
    // After the chunk has mounted and the palette is listening.
    const id = window.setTimeout(openCommandPalette, 120)
    return () => window.clearTimeout(id)
  }, [paletteReady])

  // What the palette (and other parts of the window) ask for by event.
  useEffect(() => {
    const onProduct = (event: Event) => {
      const lookupId = (event as CustomEvent<{ lookupId?: string }>).detail?.lookupId
      if (lookupId) openProduct(lookupId)
    }
    const onAction = (event: Event) => {
      const id = (event as CustomEvent<{ id?: string }>).detail?.id
      if (id === 'new-chat') startChat()
      else if (id === 'take-tour') window.dispatchEvent(new Event('kriko:tour'))
      else if (id === 'check-a-list') go('checklist')
      else if (id === 'new-estimate') {
        rememberNewEstimate()
        window.dispatchEvent(new Event('kriko:new-estimate'))
        go('estimate')
      }
    }
    // The Procurement screen may not be mounted yet: keep the request for it.
    const onEstimate = (event: Event) => {
      const estimateId = (event as CustomEvent<{ estimateId?: string }>).detail?.estimateId
      if (estimateId) rememberEstimate(estimateId)
    }
    window.addEventListener('kriko:open-product', onProduct)
    window.addEventListener('kriko:palette-action', onAction)
    window.addEventListener('kriko:open-estimate', onEstimate)
    return () => {
      window.removeEventListener('kriko:open-product', onProduct)
      window.removeEventListener('kriko:palette-action', onAction)
      window.removeEventListener('kriko:open-estimate', onEstimate)
    }
  }, [openProduct, startChat, go])

  return (
    <MotionConfig reducedMotion={m.on ? 'never' : 'always'}>
      <div className="app" onPointerOver={warm} onFocus={warm}>
        <PixelSprites />
        <Motes />
        <Rail screen={screen} onNavigate={go} onNewChat={startChat} queueCount={active} attention={attention} />
        <div className="shell-main">
          <TopStrip onNavigate={go} />
          {(engine.mode === 'live' && !engine.agentAvailable) || notice ? (
            <div className="shell-notices">
              {engine.mode === 'live' && !engine.agentAvailable && (
                <aside className="k-notice" data-tone="warn" role="status">
                  <span>No research agent is ready. Set one up before asking Kriko to research a product.</span>
                  <button className="k-btn" data-size="sm" onClick={() => showDrawer('agents')}>
                    Choose or install an agent
                  </button>
                  <button className="k-btn" data-size="sm" data-kind="quiet" onClick={() => showDrawer('settings')}>
                    Add a provider key
                  </button>
                </aside>
              )}
              {notice && (
                <aside className="k-notice" role="status">
                  <span>{notice}</span>
                  <button className="k-btn" data-size="sm" data-kind="quiet" onClick={() => setNotice('')}>
                    Dismiss
                  </button>
                </aside>
              )}
            </div>
          ) : null}
          <main className="stage">
            <AnimatePresence mode="popLayout" initial={false} custom={direction}>
              <motion.div
                key={screen + (product ?? '')}
                ref={pageRef}
                className="page"
                custom={direction}
                variants={{
                  enter: (d: number) => ({ opacity: 0, x: m.d(16) * d }),
                  center: { opacity: 1, x: 0 },
                  exit: (d: number) => ({ opacity: 0, x: -m.d(16) * d }),
                }}
                initial="enter"
                animate="center"
                exit="exit"
                transition={m.tx.soft}
                onAnimationStart={() => pageRef.current?.setAttribute('data-moving', 'true')}
                onAnimationComplete={() => pageRef.current?.removeAttribute('data-moving')}
              >
                <Suspense fallback={<PageSkeleton />}>
                  {screen === 'chat' && !product && <ChatScreen onOpen={openProduct} onAction={performAction} />}
                  {screen === 'chat' && product && <ProductScreen lookupId={product} onBack={() => go('chat')} onCompare={() => go('compare')} />}
                  {screen === 'compare' && <CompareScreen />}
                  {screen === 'checklist' && <CheckListScreen onOpen={openProduct} />}
                  {screen === 'prices' && <PricesScreen />}
                  {screen === 'estimate' && <EstimateScreen />}
                  {screen === 'queue' && <QueueScreen onOpen={openProduct} />}
                  {screen === 'history' && (
                    <PanelPage title="History">
                      <ChatsList onOpen={() => go('chat')} />
                      <HistoryPanel onOpen={openProduct} />
                    </PanelPage>
                  )}
                  {screen === 'foryou' && (
                    <PanelPage title="For you">
                      <ForYouPanel onOpen={openProduct} />
                    </PanelPage>
                  )}
                  {screen === 'catalogs' && (
                    <PanelPage title="Catalogs">
                      <CatalogsPanel onOpen={openProduct} />
                    </PanelPage>
                  )}
                  {screen === 'sites' && (
                    <PanelPage title="Sites">
                      <SitesPanel />
                    </PanelPage>
                  )}
                  {screen === 'settings' && <SettingsScreen key={seq} initial={section} />}
                </Suspense>
              </motion.div>
            </AnimatePresence>
          </main>
        </div>
        {paletteReady && (
          <Suspense fallback={null}>
            <CommandPalette />
          </Suspense>
        )}
        {tourReady && (
          <Suspense fallback={null}>
            <Tour onStart={() => go('chat')} />
          </Suspense>
        )}
      </div>
    </MotionConfig>
  )
}

export default function App() {
  return (
    <QueueProvider>
      <CompareProvider>
        <ChatProvider>
          <Shell />
        </ChatProvider>
      </CompareProvider>
    </QueueProvider>
  )
}
