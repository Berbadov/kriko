import { Icon } from './Icon'

/** The mark of the agent that wrote an answer. Each is a small shape of its own on
 *  a tile in its own colour, so a thread of answers shows who said what at a glance.
 *  They are Kriko's own drawings, not the makers' logos. */

type Look = { tone: string; glyph: 'burst' | 'prompt' | 'peak' | 'blocks' | 'pointer' | 'chip' | 'spark' }

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

function Glyph({ glyph, size }: { glyph: Look['glyph']; size: number }) {
  if (glyph === 'chip') return <Icon name="cpu" size={size} />
  if (glyph === 'spark') return <Icon name="spark" size={size} />
  const lines: Record<string, string> = {
    burst: 'M12 4v16M4 12h16M6.3 6.3l11.4 11.4M17.7 6.3 6.3 17.7',
    prompt: 'M6 8l5 4-5 4M13 17h5',
    peak: 'M12 5l7 14H5ZM9 14h6',
    pointer: 'M6 4l12 7-5 1.6L10.6 18Z',
  }
  if (glyph === 'blocks') {
    // Pixel blocks in the shape of an M, as the app's own dither draws.
    const cells: [number, number][] = [[4, 5], [4, 9], [4, 13], [4, 17], [8, 9], [12, 13], [16, 9], [20, 5], [20, 9], [20, 13], [20, 17]]
    return (
      <svg viewBox="0 0 24 24" width={size} height={size} aria-hidden="true" fill="currentColor" stroke="none">
        {cells.map(([x, y]) => (
          <rect key={`${x}-${y}`} x={x - 2} y={y - 2} width="4" height="4" rx="0.6" />
        ))}
      </svg>
    )
  }
  return (
    <svg className="icon" viewBox="0 0 24 24" width={size} height={size} aria-hidden="true">
      <path d={lines[glyph]} />
    </svg>
  )
}

export function AgentMark({ id, size = 28 }: { id: string; size?: number }) {
  const look = lookOf(id)
  return (
    <span className="agent-mark" style={{ '--tone': look.tone, width: size, height: size } as React.CSSProperties} aria-hidden="true">
      <Glyph glyph={look.glyph} size={Math.round(size * 0.58)} />
    </span>
  )
}
