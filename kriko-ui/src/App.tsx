import { useCallback, useEffect, useState } from 'react'
import { AnimatePresence, MotionConfig, motion } from 'motion/react'
import { usePrefs } from './prefs'
import { ChatProvider, useChat } from './chat'
import { CompareProvider, useCompare } from './compare'
import { useAttention } from './engine/buyer'
import { useEngine } from './engine/Engine'
import { post } from './engine/api'
import { useHandoff, type Landing } from './handoff'
import { QueueProvider, useQueue } from './queue'
import type { AppAction } from './activity/run'
import { ChatScreen } from './screens/Chat'
import { CompareScreen } from './screens/Compare'
import { EstimateScreen } from './screens/Estimate'
import { ProductScreen } from './screens/Product'
import { PricesScreen } from './screens/Prices'
import { SettingsScreen } from './screens/Settings'
import { Motes } from './dust/Motes'
import { PixelSprites } from './ui/ProductGlyph'
import { QueueScreen } from './screens/Queue'
import { Tour } from './tour/Tour'
import { DRAWER_EVENT, ORDER, RAIL_ORDER, routeFor, showDrawer, type Screen } from './ui/drawerEvents'
import { Rail, TopStrip } from './ui/Rail'
import { PanelPage } from './ui/PanelPage'
import { CatalogsPanel } from './ui/panels/Catalogs'
import { ForYouPanel } from './ui/panels/ForYou'
import { HistoryPanel } from './ui/panels/History'
import { SitesPanel } from './ui/panels/Sites'

/** Named places the agent or a link can ask for, by the screen they are. */
const TARGETS: Record<string, Screen> = {
  chat: 'chat',
  compare: 'compare',
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
  const { active } = useQueue()
  const { add } = useCompare()
  const attention = useAttention()
  const { newChat } = useChat()
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

  const startChat = useCallback(() => {
    newChat()
    go('chat')
  }, [newChat, go])

  return (
    <MotionConfig reducedMotion={m.on ? 'never' : 'always'}>
      <div className="app">
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
              >
                {screen === 'chat' && !product && <ChatScreen onOpen={openProduct} onAction={performAction} />}
                {screen === 'chat' && product && <ProductScreen lookupId={product} onBack={() => go('chat')} onCompare={() => go('compare')} />}
                {screen === 'compare' && <CompareScreen />}
                {screen === 'prices' && <PricesScreen />}
                {screen === 'estimate' && <EstimateScreen />}
                {screen === 'queue' && <QueueScreen onOpen={openProduct} />}
                {screen === 'history' && (
                  <PanelPage title="History">
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
              </motion.div>
            </AnimatePresence>
          </main>
        </div>
        <Tour onStart={() => go('chat')} />
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
