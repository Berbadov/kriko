import antigravity from '../assets/agents/antigravity.svg?raw'
import claude from '../assets/agents/claude.svg?raw'
import claudeCode from '../assets/agents/claudecode.svg?raw'
import codex from '../assets/agents/codex.svg?raw'
import cursor from '../assets/agents/cursor.svg?raw'
import mistral from '../assets/agents/mistral-color.svg?raw'
import { Icon } from './Icon'

/** The mark of the agent that wrote an answer: the maker's own logo, on a quiet tile,
 *  so a thread of answers shows who said what at a glance. The logos are the makers'
 *  trademarks, shown only to say which agent answered (see `assets/agents/NOTICE.md`).
 *  The local model and any agent without a logo keep Kriko's own drawing.
 *
 *  `state` moves the tile the way the agent is doing: a ring runs round it while it
 *  works, it breathes while it waits, it greys with an amber ring when paused, it
 *  flashes mint once when done and shakes in red when it failed. */

export type AgentState = 'idle' | 'working' | 'waiting' | 'paused' | 'done' | 'failed'

/** A logo, the colour it is drawn in (`currentColor` in the file), or `own` when the
 *  file carries its own colours. */
type Look = { svg?: string; tone: string; own?: boolean; glyph?: 'chip' | 'spark' }

const LOOKS: Record<string, Look> = {
  'claude-code': { svg: claudeCode, tone: '#D97757' },
  'claude-desktop': { svg: claude, tone: '#D97757' },
  codex: { svg: codex, tone: 'var(--ink)' },
  'antigravity-cli': { svg: antigravity, tone: '#3186FF' },
  'mistral-vibe': { svg: mistral, tone: 'var(--ink)', own: true },
  'mistral-api': { svg: mistral, tone: 'var(--ink)', own: true },
  cursor: { svg: cursor, tone: 'var(--ink)' },
  local: { tone: '#3ddc97', glyph: 'chip' },
}

const FALLBACK: Look = { tone: '#7b98ff', glyph: 'spark' }

export const lookOf = (id: string): Look => LOOKS[id] ?? FALLBACK

/** The files are sized `1em` with an inline style; the tile sizes them instead. */
const bare = (svg: string) => svg.replace(/ height="1em"| width="1em"| style="[^"]*"/g, '')

export function AgentMark({ id, size = 28, state = 'idle' }: { id: string; size?: number; state?: AgentState }) {
  const look = lookOf(id)
  const inner = Math.round(size * 0.62)
  return (
    <span className="agent-mark" data-state={state} style={{ '--tone': look.tone, width: size, height: size } as React.CSSProperties} aria-hidden="true">
      {look.svg ? (
        <span className="agent-logo" style={{ width: inner, height: inner }} dangerouslySetInnerHTML={{ __html: bare(look.svg) }} />
      ) : (
        <span className="agent-logo">
          <Icon name={look.glyph === 'chip' ? 'cpu' : 'spark'} size={inner} />
        </span>
      )}
    </span>
  )
}
