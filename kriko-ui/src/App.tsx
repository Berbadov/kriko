import { useCallback, useEffect, useState } from 'react'
import { AnimatePresence, MotionConfig, motion } from 'motion/react'
import { usePrefs } from './prefs'
import { ChatProvider, useChat } from './chat'
import { CompareProvider, useCompare } from './compare'
import { useHandoff, type Landing } from './handoff'
import { QueueProvider, useQueue } from './queue'
import { ChatScreen } from './screens/Chat'
import { CompareScreen } from './screens/Compare'
import { ProductScreen } from './screens/Product'
import { QueueScreen } from './screens/Queue'
import { Tour } from './tour/Tour'
import { Drawer } from './ui/Drawer'
import { DRAWER_EVENT } from './ui/drawerEvents'
import { ORDER, Rail, type Screen } from './ui/Rail'

function Shell() {
  const { motion: m } = usePrefs()
  const { active } = useQueue()
  const { add } = useCompare()
  const chat = useChat()
  const [{ screen, direction, product }, setNav] = useState<{ screen: Screen; direction: number; product: string | null }>({ screen: 'chat', direction: 1, product: null })
  const [collapsed, setCollapsed] = useState(false)
  const [drawer, setDrawer] = useState(false)
  /** A panel the drawer should open on, asked for by the tour. */
  const [drawerPanel, setDrawerPanel] = useState<string | null>(null)

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
    setNav((current) => ({
      screen: next,
      direction: ORDER.indexOf(next) >= ORDER.indexOf(current.screen) ? 1 : -1,
      product: null,
    }))
  }, [])

  const openProduct = useCallback((lookupId: string) => {
    setDrawer(false)
    setNav((current) => ({ screen: 'chat', direction: current.screen === 'chat' ? 1 : -1, product: lookupId }))
  }, [])

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

  const closeDrawer = useCallback(() => setDrawer(false), [])

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
        <Rail screen={screen} onNavigate={go} collapsed={collapsed} onCollapse={() => setCollapsed((v) => !v)} onMore={() => setDrawer(true)} onNewChat={startChat} onOpenChat={showChat} queueCount={active} />
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
              {screen === 'chat' && !product && <ChatScreen onOpen={openProduct} />}
              {screen === 'chat' && product && <ProductScreen lookupId={product} onBack={() => go('chat')} onCompare={() => go('compare')} />}
              {screen === 'compare' && <CompareScreen />}
              {screen === 'queue' && <QueueScreen />}
            </motion.div>
          </AnimatePresence>
        </main>
        <Drawer open={drawer} panel={drawerPanel} onClose={closeDrawer} offset={collapsed ? 68 : 244} onOpen={openProduct} />
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
