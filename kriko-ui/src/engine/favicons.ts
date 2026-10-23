import { useCallback, useEffect, useState } from 'react'
import { useEngine } from './Engine'
import { get, inShell } from './api'

/** A site's own icon, from the engine's one door to it.
 *
 *  `GET /api/favicon` takes a host and answers with the image itself, or a
 *  404 when the site declares none: the engine fetches it from the site,
 *  checks the destination first, and keeps a copy for thirty days. The window
 *  cannot fetch a site, which is why the ask goes to the engine — and the
 *  shell's bridge between the page and the engine carries JSON text, not
 *  bytes, so the page loads the image from the engine itself.
 *
 *  Which engine address that is depends on how the window is running. In
 *  development the page and the engine share an origin (Vite forwards `/api`),
 *  so the path is relative. The packaged window's origin is its own, so it
 *  uses the engine's fixed listener — the one `/api/extension` reports — and
 *  only while that listener is this engine's own (`port_is_ours`). A port
 *  that belongs to something else is never asked: another program's answer
 *  is not this site's mark.
 *
 *  Three rules keep an absent or slow icon from becoming a hole or a storm:
 *  a row draws a letter generated from the host first and the image over it,
 *  so there is always a mark; a host the engine answered "no icon" for is
 *  remembered for the session and not asked again; and nothing is asked at
 *  all unless the window is talking to a live engine, so demo mode and an
 *  offline window make no request. */

/** The address an icon may be loaded from: "" for the page's own origin (the
 *  development proxy), or null when there is no engine address the page may
 *  use. Resolved once per session. */
let origin: Promise<string | null> | null = null

function iconOrigin(): Promise<string | null> {
  if (!inShell()) return Promise.resolve('')
  origin ??= get<{ port?: number; port_is_ours?: boolean }>('/api/extension', 4000)
    .then((info) => {
      if (info.port_is_ours && info.port) return `http://127.0.0.1:${info.port}`
      // A development shell has the page's own origin to fall back on; the
      // packaged one does not, and a relative ask would be a request to the
      // window's own asset server rather than to the engine.
      return import.meta.env.DEV ? '' : null
    })
    .catch(() => {
      // Not an answer, so not remembered: the next row may find the engine up.
      origin = null
      return null
    })
  return origin
}

/** Hosts the engine said it has no icon for. Asked once, never in a loop. */
const missing = new Set<string>()

/** The host a row draws its mark for: the engine's own `host` when it named
 *  one, otherwise the page address it gave. Nothing is invented. */
export function siteHost(host: string, url: string): string {
  const named = (host || '').trim()
  if (named) return named
  try {
    return new URL(url).hostname
  } catch {
    return ''
  }
}

/** The letter a row falls back to, derived from the host alone. The engine's
 *  own route calls the fallback a monogram, and this is that mark. */
export function siteLetter(host: string): string {
  const name = (host || '').trim().replace(/^www\./i, '')
  const first = /[a-z0-9]/i.exec(name)
  return first ? first[0].toUpperCase() : ''
}

/** The icon's address for one host, and a way to say it did not arrive.
 *
 *  The address is null until the engine is known to be reachable, whenever it
 *  has already said this host has no icon, and after an image failed to load.
 *  The caller draws its letter either way. */
export function useSiteIcon(host: string): [src: string | null, missed: () => void] {
  const { mode } = useEngine()
  const [base, setBase] = useState<string | null>()
  const [failed, setFailed] = useState(false)
  const name = host.trim()

  useEffect(() => {
    if (mode !== 'live' || !name) return
    let alive = true
    void iconOrigin().then((found) => {
      if (alive) setBase(found)
    })
    return () => {
      alive = false
    }
  }, [mode, name])

  const missed = useCallback(() => {
    if (name) missing.add(name)
    setFailed(true)
  }, [name])

  const src =
    mode === 'live' && base !== undefined && base !== null && !failed && !missing.has(name)
      ? `${base}/api/favicon?host=${encodeURIComponent(name)}`
      : null
  return [src, missed]
}
