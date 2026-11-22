import { useMemo, type CSSProperties } from 'react'
import { rng } from './engine'
import { useAfterIdle } from '../idle'
import { useDustMotion } from './DustField'
import { lowCores } from './ticker'

/**
 * A few grains of dust that float across the whole window, behind everything.
 * The same material as the sky, at a whisper: a handful of motes, each rising
 * and swaying on its own slow clock. CSS only (transform and opacity, on the
 * compositor), so it costs no frame loop. Calm halves them; still draws none; a
 * machine with few cores gets half. Nothing is drawn until the
 * window has been idle once, so the motes are never on the way to a usable Ask.
 */
export function Motes({ count = 22 }: { count?: number }) {
  const motion = useDustMotion()
  const ready = useAfterIdle()
  const scale = lowCores() ? 0.5 : 1
  const n = !ready || motion === 'still' ? 0 : Math.round((motion === 'calm' ? count / 2 : count) * scale)
  const motes = useMemo(() => {
    const random = rng(41)
    return Array.from({ length: count }, () => ({
      x: random() * 100,
      size: 1 + random() * 2,
      dur: 26 + random() * 30,
      delay: -random() * 50,
      sway: 8 + random() * 24,
      peak: 0.18 + random() * 0.32,
    }))
  }, [count])
  if (!n) return null
  return (
    <div className="motes" aria-hidden="true">
      {motes.slice(0, n).map((mote, i) => (
        <i
          key={i}
          style={{
            '--x': `${mote.x}%`,
            '--s': `${mote.size}px`,
            '--d': `${mote.dur}s`,
            '--delay': `${mote.delay}s`,
            '--sway': `${mote.sway}px`,
            '--peak': mote.peak,
          } as CSSProperties}
        />
      ))}
    </div>
  )
}
