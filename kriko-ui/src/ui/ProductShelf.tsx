import type { CSSProperties } from 'react'
import { SHELF_SPRITES } from './shelfSprites'

type Ware = 'boiler' | 'kettle' | 'monitor' | 'washer' | 'car'

/** One column of the shelf: boxes from the floor up (heights in box units), and the product on top. */
interface Stack { boxes: number[]; ware?: Ware; wide?: boolean }

const LEFT: Stack[] = [
  { boxes: [2, 1], ware: 'boiler' },
  { boxes: [1], ware: 'car', wide: true },
  { boxes: [0.5], ware: 'kettle' },
]
const RIGHT: Stack[] = [
  { boxes: [1], ware: 'monitor' },
  { boxes: [1, 1, 1], ware: 'washer' },
]

/**
 * The home's back wall: product boxes stacked like stairs at both edges, with a
 * small pixel product sitting on each stack. Decoration only: drawn behind the
 * question, hidden from assistive tech, shrunk or dropped on a narrow window.
 * The products hop now and then; with reduced motion they stay put.
 */
export function ProductShelf() {
  let order = 0
  const side = (stacks: Stack[], name: string) => (
    <div className={`shelf-side shelf-${name}`}>
      {stacks.map((stack, i) => (
        <span key={i} className="shelf-stack" data-wide={stack.wide || undefined}>
          {stack.ware && (
            <svg className="shelf-ware" viewBox={stack.ware === 'car' ? '0 0 16 9' : '0 0 10 10'} style={{ '--d': order++ } as CSSProperties}>
              <use href={`#px-${stack.ware}`} />
            </svg>
          )}
          {[...stack.boxes].reverse().map((height, j) => (
            <i key={j} className="shelf-box" style={{ '--h': height, '--d': order++ } as CSSProperties} />
          ))}
        </span>
      ))}
    </div>
  )
  return (
    <div className="shelf" aria-hidden="true">
      <svg width="0" height="0" style={{ position: 'absolute' }} dangerouslySetInnerHTML={{ __html: SHELF_SPRITES }} />
      {side(LEFT, 'left')}
      {side(RIGHT, 'right')}
    </div>
  )
}
