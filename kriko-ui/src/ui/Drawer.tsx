import { useEffect, useRef, useState, type ComponentType } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { useEngine } from '../engine/Engine'
import { DRAWER } from '../mock/data'
import { usePrefs } from '../prefs'
import { Icon } from './Icon'
import { AgentsPanel } from './panels/Agents'
import { CatalogsPanel } from './panels/Catalogs'
import { HistoryPanel } from './panels/History'
import { LocalPanel } from './panels/Local'
import { SettingsPanel } from './panels/Settings'
import { SitesPanel } from './panels/Sites'
import { SetupPanel } from './panels/Setup'
import { BackupsPanel } from './panels/Backups'

/** The places that have a panel. The others are listed, and say they are not ready. */
const PANELS: Record<string, ComponentType<{ onOpen: (lookupId: string) => void }>> = {
  setup: SetupPanel,
  backups: BackupsPanel,
  agents: AgentsPanel,
  browse: CatalogsPanel,
  history: HistoryPanel,
  local: LocalPanel,
  settings: SettingsPanel,
  sites: SitesPanel,
}

/** Settings and the places that are not Chat, Compare or Queue. It opens at the
 *  left, beside the rail, and `offset` is the width the rail has now. */
export function Drawer({ open, panel: asked, onClose, offset, onOpen }: { open: boolean; panel?: string | null; onClose: () => void; offset: number; onOpen: (lookupId: string) => void }) {
  const { motion: m } = usePrefs()
  const panel = useRef<HTMLDivElement>(null)
  const engine = useEngine()
  const [inside, setInside] = useState<string | null>(null)

  // Closing the drawer puts it back at the list, so the next opening starts there.
  useEffect(() => {
    setInside(open ? (asked ?? null) : null)
  }, [open, asked])

  useEffect(() => {
    if (!open) return
    // Where the focus was, so closing can put it back. Without this a keyboard
    // user closes the drawer and lands at the top of the document, with no way
    // to tell where they are — the control that opened it is the answer.
    const cameFrom = document.activeElement as HTMLElement | null
    panel.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (inside) setInside(null)
      else onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      if (cameFrom && document.contains(cameFrom)) cameFrom.focus()
    }
  }, [open, onClose, inside])

  const item = DRAWER.find((entry) => entry.id === inside)
  const Body = inside ? PANELS[inside] : undefined

  return (
    <AnimatePresence>
      {open && (
        <>
          <motion.div className="scrim" style={{ left: offset + 20 }} onClick={onClose} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={m.tx.soft} />
          <motion.div
            ref={panel}
            className="drawer"
            data-wide={Boolean(Body)}
            role="dialog"
            aria-label={item?.title ?? 'More'}
            tabIndex={-1}
            style={{ left: offset + 20 }}
            initial={{ x: m.on ? -380 : 0, opacity: m.on ? 0.4 : 1 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: m.on ? -380 : 0, opacity: 0 }}
            transition={m.tx.spring}
          >
            <header className="drawer-head">
              {Body && (
                <button className="icon-btn" onClick={() => setInside(null)} aria-label="Back">
                  <Icon name="collapse" />
                </button>
              )}
              <h2>{Body ? item?.title : 'More'}</h2>
              <button className="icon-btn" onClick={onClose} aria-label="Close">
                <Icon name="x" />
              </button>
            </header>

            <AnimatePresence mode="wait" initial={false}>
              {Body ? (
                <motion.div
                  key={inside}
                  initial={{ opacity: 0, x: m.d(24) }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: m.d(24) }}
                  transition={m.tx.soft}
                >
                  <Body onOpen={onOpen} />
                </motion.div>
              ) : (
                <motion.div key="list" initial={{ opacity: 0, x: -m.d(24) }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -m.d(24) }} transition={m.tx.soft}>
                  <p className="engine-line" data-mode={engine.mode}>
                    <i />
                    {engine.mode === 'live' ? 'Engine connected' : engine.mode === 'checking' ? 'Looking for the engine' : 'Demo data. No engine answers.'}
                    {engine.mode === 'demo' && <button onClick={engine.retry}>Try again</button>}
                  </p>
                  {engine.problem && <p className="error-note">{engine.problem}</p>}

                  <ul className="drawer-list">
                    {DRAWER.map((entry, index) => {
                      const ready = entry.id in PANELS
                      return (
                        <motion.li
                          key={entry.id}
                          initial={{ opacity: 0, x: -m.d(14) }}
                          animate={{ opacity: 1, x: 0 }}
                          transition={{ ...(m.tx.soft as object), delay: m.on ? 0.05 + index * 0.035 : 0 }}
                        >
                          <button className="drawer-item" disabled={!ready} onClick={() => setInside(entry.id)}>
                            <span className="drawer-icon">
                              <Icon name={entry.icon} size={17} />
                            </span>
                            <span>
                              <strong>{entry.title}</strong>
                              <small>{entry.note}</small>
                            </span>
                            {ready ? <Icon name="expand" size={15} /> : <span className="soon">Soon</span>}
                          </button>
                        </motion.li>
                      )
                    })}
                  </ul>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  )
}
