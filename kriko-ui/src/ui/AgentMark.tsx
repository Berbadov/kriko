import { PixIcon, type PixState } from './PixIcon'

/** The mark of an agent: a pixel drawing of its own, in its own colour, on a
 *  dark tile, so a thread of answers shows who said what at a glance. They are
 *  Kriko's own drawings, not the makers' logos. `state` moves the cells: a scan
 *  while it works, a blink while it waits, amber when paused, red when it fails
 *  (`ui/PixIcon.tsx`). */

type Look = { tone: string; glyph: string }

const LOOKS: Record<string, Look> = {
  'claude-code': { tone: '#e0825f', glyph: 'burst' },
  'claude-desktop': { tone: '#e0825f', glyph: 'burst' },
  codex: { tone: '#56d6a0', glyph: 'prompt' },
  'antigravity-cli': { tone: '#7b98ff', glyph: 'peak' },
  'mistral-vibe': { tone: '#ff9a3d', glyph: 'blocks' },
  'mistral-api': { tone: '#ff9a3d', glyph: 'blocks' },
  cursor: { tone: '#c3c8d6', glyph: 'pointer' },
  local: { tone: '#3ddc97', glyph: 'chip' },
}

const FALLBACK: Look = { tone: '#7b98ff', glyph: 'spark' }

export const lookOf = (id: string): Look => LOOKS[id] ?? FALLBACK

export function AgentMark({ id, size = 28, state = 'idle' }: { id: string; size?: number; state?: PixState }) {
  const look = lookOf(id)
  return (
    <span className="agent-mark" data-state={state} style={{ '--tone': look.tone, width: size, height: size } as React.CSSProperties} aria-hidden="true">
      <PixIcon name={look.glyph} size={Math.round(size * 0.66)} state={state} tone={look.tone} />
    </span>
  )
}
