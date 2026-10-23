import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { Evidence, Standing } from '../compare/checks'
import { siteHost, siteLetter, useSiteIcon } from '../engine/favicons'
import { ExternalLink } from './ExternalLink'

/** The sources behind a claim, as chips: the site's own icon (asked of the
 *  engine, with a letter from the host as the fallback), the mark for where the
 *  source stands, and the site. The exact quote opens on hover, focus or tap.
 *  The shapes are the evidence mark's own (filled, half, ring), so colour is
 *  never the only cue. A source the engine could not place draws no mark rather
 *  than a guess. The extension panel draws the same chip
 *  (`extension/hover_lite/claim_card.js`). */

const STANDING_WORD = { trusted: 'Trusted', neutral: 'Neutral', low: 'Low' } as const

const LIT = { trusted: 3, neutral: 2, low: 1 } as const

/** Three bars that rise like a signal, lit by where the source stands. */
function TierMeter({ standing }: { standing: Standing }) {
  return (
    <span className="claim-meter" data-lit={LIT[standing]} aria-hidden="true">
      <i />
      <i />
      <i />
    </span>
  )
}

/** The site's own mark for a source row: the engine's icon over a letter
 *  generated from the host. The letter is drawn first and kept underneath, so
 *  the row carries a mark before the engine answers, when the engine says the
 *  site has no icon, when the image will not load, and when there is no engine
 *  at all. Nothing here is invented: the icon is the engine's own fetch, and
 *  the letter is the host the row already carries. */
export function SiteMark({ host }: { host: string }) {
  const [src, missed] = useSiteIcon(host)
  const letter = siteLetter(host)
  if (!letter) return null
  return (
    <span className="site-mark" aria-hidden="true">
      <span className="site-mark-letter">{letter}</span>
      {src && <img src={src} alt="" loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={missed} />}
    </span>
  )
}

/** One card is open at a time, wherever the chips are. */
let closeOpen: (() => void) | null = null

const kindOf = (tier?: string) => (tier ? tier.replaceAll('_', ' ') : '')

export function ClaimChip({ source, compact = false }: { source: Evidence; compact?: boolean }) {
  const id = useId()
  const chip = useRef<HTMLButtonElement>(null)
  const card = useRef<HTMLDivElement>(null)
  const timer = useRef<number>(0)
  const [open, setOpen] = useState(false)
  const [at, setAt] = useState<{ left: number; top: number } | null>(null)
  const site = source.host || source.url
  const mark = siteHost(source.host, source.url)
  const word = source.standing ? STANDING_WORD[source.standing] : ''
  const against = source.stance.toLowerCase() === 'refutes'

  const close = useCallback(() => {
    window.clearTimeout(timer.current)
    setOpen(false)
    if (closeOpen === close) closeOpen = null
  }, [])
  const show = () => {
    window.clearTimeout(timer.current)
    if (closeOpen && closeOpen !== close) closeOpen()
    closeOpen = close
    setOpen(true)
  }
  const later = () => {
    window.clearTimeout(timer.current)
    timer.current = window.setTimeout(close, 220)
  }
  useEffect(() => () => {
    window.clearTimeout(timer.current)
    if (closeOpen === close) closeOpen = null
  }, [close])

  // Placed under the chip, or above it when the window has no room below.
  useLayoutEffect(() => {
    if (!open || !chip.current || !card.current) return
    const r = chip.current.getBoundingClientRect()
    const w = card.current.offsetWidth
    const h = card.current.offsetHeight
    const below = r.bottom + 8
    setAt({
      left: Math.max(12, Math.min(r.left, window.innerWidth - w - 12)),
      top: below + h > window.innerHeight - 12 && r.top - h - 8 > 12 ? r.top - h - 8 : below,
    })
  }, [open])

  useEffect(() => {
    if (!open) return
    const out = (event: Event) => {
      if (!chip.current?.contains(event.target as Node) && !card.current?.contains(event.target as Node)) close()
    }
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        close()
        chip.current?.focus()
      }
    }
    const away = () => close()
    document.addEventListener('pointerdown', out)
    window.addEventListener('keydown', key)
    window.addEventListener('resize', away)
    window.addEventListener('scroll', away, true)
    return () => {
      document.removeEventListener('pointerdown', out)
      window.removeEventListener('keydown', key)
      window.removeEventListener('resize', away)
      window.removeEventListener('scroll', away, true)
    }
  }, [open, close])

  const hover = typeof window.matchMedia === 'function' && window.matchMedia('(hover: hover)').matches
  return (
    <>
      <button
        ref={chip}
        type="button"
        className="claim-chip"
        data-standing={source.standing}
        data-compact={compact || undefined}
        data-stance={against ? 'against' : undefined}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        aria-label={`Source ${site}${word ? `, ${word.toLowerCase()}` : ''}${against ? ', disputes this' : ''}`}
        onClick={() => (open ? close() : show())}
        onMouseEnter={hover ? show : undefined}
        onMouseLeave={hover ? later : undefined}
      >
        {mark && <SiteMark host={mark} />}
        {source.standing && <TierMeter standing={source.standing} />}
        {!compact && <span className="claim-site">{site}</span>}
      </button>
      {open &&
        createPortal(
          <div
            ref={card}
            id={id}
            className="claim-card"
            data-standing={source.standing}
            role="dialog"
            aria-label={`Evidence from ${site}`}
            style={{ left: at?.left ?? 0, top: at?.top ?? 0, visibility: at ? 'visible' : 'hidden' }}
            onMouseEnter={() => window.clearTimeout(timer.current)}
            onMouseLeave={hover ? later : undefined}
          >
            <div className="claim-card-head" data-standing={source.standing}>
              {source.standing && <TierMeter standing={source.standing} />}
              <strong>{site}</strong>
              {word && <span className="mono claim-card-word">{word}</span>}
            </div>
            {source.quote ? <blockquote>{source.quote}</blockquote> : <p className="claim-card-none">No quote is recorded for this source.</p>}
            {(against || kindOf(source.tier)) && (
              <p className="claim-card-meta mono">
                {[kindOf(source.tier), against ? 'Disputes this claim' : ''].filter(Boolean).join(' · ')}
              </p>
            )}
            <div className="claim-card-acts">
              {source.url && <ExternalLink href={source.url}>Open the page</ExternalLink>}
              <button type="button" onClick={() => { close(); chip.current?.focus() }}>
                Close
              </button>
            </div>
          </div>,
          document.body,
        )}
    </>
  )
}

/** The chips of one claim. Nothing is drawn for a claim that cites no page. */
export function ClaimSources({ sources }: { sources: Evidence[] }) {
  if (sources.length === 0) return null
  return (
    <span className="claim-sources">
      {sources.map((source, i) => (
        <ClaimChip key={`${source.url || source.host}-${i}`} source={source} />
      ))}
    </span>
  )
}
