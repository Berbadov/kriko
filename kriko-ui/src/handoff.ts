import { useEffect } from 'react'
import type { Screen } from './ui/Rail'

/** The browser extension hands a product to this window. It names a route:
 *  `check`, `result/<id>`, `questions/<id>` or `compare/<id>`. The engine
 *  prints the route for the shell, the shell raises the window and sends the
 *  route here as a `focus-route` event. A browser tab gets it as `#/route`. */

export interface Landing {
  screen: Screen
  /** A saved check to open, for `result` and `questions`. */
  product?: string
  /** A saved check to put on the board, for `compare`. */
  board?: string
}

export function parseRoute(raw: string): Landing | null {
  const [name, id] = raw.replace(/^#?\/?/, '').split('/')
  switch (name) {
    case 'check':
    case 'chat':
      return { screen: 'chat' }
    case 'result':
    case 'questions':
      return id ? { screen: 'chat', product: decodeURIComponent(id) } : { screen: 'chat' }
    case 'compare':
      return { screen: 'compare', board: id ? decodeURIComponent(id) : undefined }
    case 'queue':
      return { screen: 'queue' }
    default:
      return null
  }
}

export function useHandoff(onLand: (landing: Landing) => void) {
  useEffect(() => {
    const fromHash = () => {
      const landing = parseRoute(window.location.hash)
      if (landing) onLand(landing)
    }
    fromHash()
    window.addEventListener('hashchange', fromHash)

    let stop: (() => void) | undefined
    let gone = false
    if ('__TAURI_INTERNALS__' in window) {
      import('@tauri-apps/api/event')
        .then(({ listen }) =>
          listen<string>('focus-route', (event) => {
            const landing = parseRoute(event.payload)
            if (landing) onLand(landing)
          }),
        )
        .then((unlisten) => {
          if (gone) unlisten()
          else stop = unlisten
        })
        .catch(() => undefined)
    }
    return () => {
      gone = true
      window.removeEventListener('hashchange', fromHash)
      stop?.()
    }
  }, [onLand])
}
