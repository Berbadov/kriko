import { useEffect, useState } from 'react'
import { inShell } from '../engine/api'

/**
 * The window's own title bar, drawn by the app so it carries the app's colours.
 *
 * Windows draws a system bar above the page (its own colour, its own title),
 * and the page can neither tint nor remove it. The Windows build therefore asks
 * for a window without decorations (`tauri.windows.conf.json`) and these three
 * buttons stand in for them. They sit at the right end of the app's own top bar
 * (the strip is exactly as wide as they are, so the row underneath keeps its
 * presses), and the row itself drags the window. A window that kept its system
 * bar (macOS, the browser, demo mode) asks the window itself and draws nothing.
 *
 * Close is not Quit. It reaches the shell's close handler, which hides the
 * window and leaves the engine running.
 */
export function TitleBar() {
  const [bare, setBare] = useState(false)
  const [maximized, setMaximized] = useState(false)

  useEffect(() => {
    if (!inShell()) return
    let off: (() => void) | undefined
    let gone = false
    void (async () => {
      const { getCurrentWindow } = await import('@tauri-apps/api/window')
      const window = getCurrentWindow()
      if (await window.isDecorated()) return
      const sync = () => window.isMaximized().then((now) => { if (!gone) setMaximized(now) }).catch(() => {})
      setBare(true)
      void sync()
      const stop = await window.onResized(() => void sync())
      if (gone) stop()
      else off = stop
    })().catch(() => {})
    return () => {
      gone = true
      off?.()
    }
  }, [])

  // The page keeps room for the buttons in its top bar only while they are there.
  useEffect(() => {
    document.documentElement.toggleAttribute('data-titlebar', bare)
    return () => document.documentElement.removeAttribute('data-titlebar')
  }, [bare])

  if (!bare) return null

  const act = (verb: 'minimize' | 'toggleMaximize' | 'close') => () => {
    void import('@tauri-apps/api/window').then(({ getCurrentWindow }) => getCurrentWindow()[verb]()).catch(() => {})
  }

  return (
    <div className="titlebar" data-tauri-drag-region>
      <div className="titlebar-controls">
        <button type="button" className="titlebar-btn" aria-label="Minimise" onClick={act('minimize')}>
          <svg viewBox="0 0 10 10" width="10" height="10" aria-hidden="true"><path d="M1 5h8" /></svg>
        </button>
        <button type="button" className="titlebar-btn" aria-label={maximized ? 'Restore' : 'Maximise'} onClick={act('toggleMaximize')}>
          {maximized
            ? <svg viewBox="0 0 10 10" width="10" height="10" aria-hidden="true"><path d="M2.5 3.5h5v5h-5zM4 3.5V1.5h4.5v5H7.5" /></svg>
            : <svg viewBox="0 0 10 10" width="10" height="10" aria-hidden="true"><path d="M1.5 1.5h7v7h-7z" /></svg>}
        </button>
        <button type="button" className="titlebar-btn close" aria-label="Close" onClick={act('close')}>
          <svg viewBox="0 0 10 10" width="10" height="10" aria-hidden="true"><path d="M1.5 1.5l7 7M8.5 1.5l-7 7" /></svg>
        </button>
      </div>
    </div>
  )
}
