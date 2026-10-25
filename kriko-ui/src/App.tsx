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
import { ProductScreen } from './screens/Product'
import { QueueScreen } from './screens/Queue'
import { Tour } from './tour/Tour'
import { Drawer } from './ui/Drawer'
import { DRAWER_EVENT, showDrawer } from './ui/drawerEvents'
import { ORDER, TopBar, type Screen } from './ui/TopBar'

function Shell() {
  const { motion: m } = usePrefs()
  const engine = useEngine()
  const { active } = useQueue()
  const { add } = useCompare()
  const attention = useAttention()
  const chat = useChat()
  const [{ screen, direction, product }, setNav] = useState<{ screen: Screen; direction: number; product: string | null }>({ screen: 'chat', direction: 1, product: null })
  const [drawer, setDrawer] = useState(false)
  /** A panel the drawer should open on, asked for by the tour. */
  const [drawerPanel, setDrawerPanel] = useState<string | null>(null)
  /** One line about a started app action, until the reader dismisses it. */
  const [notice, setNotice] = useState('')

  useEffect(() => {
    const onDrawer = (event: Event) => {
      const panel = (event as CustomEvent<{ panel: string | null }>).detail.panel
      setDrawerPanel(panel)
      setDrawer(panel !== null)
    }
    window.addEventListener(DRAWER_EVENT, onDrawer)
    return () => window.removeEventListener(DRAWER_EVENT, onDrawer)
  }, [])

  // A move to a later place enters from the right. A move to an earlier place enters from the left.
  const go = useCallback((next: Screen) => {
    setDrawer(false)
    setDrawerPanel(null)
    setNav((current) => ({
      screen: next,
      direction: ORDER.indexOf(next) >= ORDER.indexOf(current.screen) ? 1 : -1,
      product: null,
    }))
  }, [])

  const openProduct = useCallback((lookupId: string) => {
    setDrawer(false)
    setDrawerPanel(null)
    setNav((current) => ({ screen: 'chat', direction: current.screen === 'chat' ? 1 : -1, product: lookupId }))
  }, [])

  /** A named action the agent proposed. Navigation is the window's; a Quick
   *  Look is the engine's job and starts only after this press. */
  const performAction = useCallback((action: AppAction) => {
    if (action.kind === 'open') {
      const target = String(action.params?.screen || '')
      if (target === 'chat' || target === 'compare' || target === 'queue') {
        go(target)
        return
      }
      if (target === 'catalogs') showDrawer('browse')
      else if (target === 'for-you') showDrawer('foryou')
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

  // Closing puts the drawer back at its list of panels, so the next opening
  // starts there and not on whatever page was last read. `Drawer.tsx` says it
  // did this; it did not, because the panel it is handed outlived the closing.
  const closeDrawer = useCallback(() => {
    setDrawer(false)
    setDrawerPanel(null)
  }, [])

  /** The More button opens the list, never the page that was open last time. */
  const openDrawerList = useCallback(() => {
    setDrawerPanel(null)
    setDrawer(true)
  }, [])

  /**
   * The shortcuts a desktop window is expected to have.
   *
   * `App.tsx` registered exactly one key before this — the drawer event — so
   * Ctrl+1..3 did nothing, Ctrl+K did nothing, and the only way back from a
   * product page was its own Back control (`screens/Product.tsx`). Escape is
   * left to whatever has focus: the drawer and the composer both handle it, and
   * a global handler that swallowed it would break both.
   */
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return
      const digit = ['1', '2', '3'].indexOf(event.key)
      if (digit >= 0 && digit < ORDER.length) {
        event.preventDefault()
        go(ORDER[digit])
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

  // A new chat and a saved chat both open on the Chat page.
  const { newChat, open: openChat } = chat
  const startChat = useCallback(() => {
    newChat()
    go('chat')
  }, [newChat, go])
  const showChat = useCallback(
    (threadId: string) => {
      go('chat')
      void openChat(threadId)
    },
    [openChat, go],
  )

  return (
    <MotionConfig reducedMotion={m.on ? 'never' : 'always'}>
      <div className="app">
        <TopBar screen={screen} onNavigate={go} onMore={openDrawerList} onNewChat={startChat} onOpenChat={showChat} queueCount={active} attention={attention} />
        {engine.mode === 'live' && !engine.agentAvailable && (
          <aside className="engine-notice" role="status">
            <span>No research agent is ready. Set one up before asking Kriko to research a product.</span>
            <button className="btn" onClick={() => showDrawer('agents')}>Choose or install an agent</button>
            <button className="btn ghost" onClick={() => showDrawer('settings')}>Add a provider key</button>
          </aside>
        )}
        {notice && (
          <aside className="engine-notice" role="status">
            <span>{notice}</span>
            <button className="btn ghost" onClick={() => setNotice('')}>Dismiss</button>
          </aside>
        )}
        <main className="stage">
          <AnimatePresence mode="popLayout" initial={false} custom={direction}>
            <motion.div
              key={screen + (product ?? '')}
              className="page"
              custom={direction}
              variants={{
                enter: (d: number) => ({ opacity: 0, x: m.d(44) * d }),
                center: { opacity: 1, x: 0 },
                exit: (d: number) => ({ opacity: 0, x: -m.d(44) * d }),
              }}
              initial="enter"
              animate="center"
              exit="exit"
              transition={m.tx.page}
            >
              {screen === 'chat' && !product && <ChatScreen onOpen={openProduct} onAction={performAction} />}
              {screen === 'chat' && product && <ProductScreen lookupId={product} onBack={() => go('chat')} onCompare={() => go('compare')} />}
              {screen === 'compare' && <CompareScreen />}
              {screen === 'queue' && <QueueScreen />}
            </motion.div>
          </AnimatePresence>
        </main>
        <Drawer open={drawer} panel={drawerPanel} onClose={closeDrawer} offset={0} onOpen={openProduct} />
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
