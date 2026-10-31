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
 *  The tile is the agent's whole presence in the app — no second ornament beside it.
 *  Its state is drawn on the tile's own edge: a hairline ring at rest, a thin arc
 *  travelling that edge while it works, a slow pulse of the ring while it waits for
 *  the reader, an amber underbar with the logo greyed when paused, a mint seal when
 *  the answer lands, and a red underbar with one shake when it failed. */

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
      {/* The edge is one 40-unit square whatever the tile size, so the hairline
          and the arc keep their proportions from the answer head down to the pill. */}
      <svg className="agent-edge" viewBox="0 0 40 40" focusable="false">
        <circle className="agent-track" cx="20" cy="20" r="18.6" />
        <circle className="agent-arc" cx="20" cy="20" r="18.6" pathLength={100} />
        <line className="agent-rest" x1="14" y1="34.2" x2="26" y2="34.2" />
        <path className="agent-seal" d="M13.4 20.5l4 4 8.4-8.7" pathLength={1} />
      </svg>
    </span>
  )
}
