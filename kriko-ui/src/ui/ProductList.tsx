import { useState } from 'react'
import type { Product } from '../activity/run'
import { useFocus } from '../chat/focus'
import { productKey } from '../chat/view'
import { Icon } from './Icon'
import { ProductCard } from './ProductCard'
import { Fold } from './text'

/** Up to this many products are drawn as cards where they are named. More than
 *  that is a list the reader opens: the thread is for the answer, and a long run
 *  of cards pushes it off the screen. */
const SHOWN = 2

/** The products one answer named. Sources never appear here: the pages a turn
 *  read live in the column beside the thread, and this is only what was named. */
export function ProductList({ products, onOpen }: { products: Product[]; onOpen: (lookupId: string) => void }) {
  const focus = useFocus()
  /** The reader's own press. Until they make one, the list is open only for a product picked in the column. */
  const [chosen, setChosen] = useState<boolean | null>(null)
  const lit = products.some((product) => focus.key === productKey(product.id))
  const open = chosen ?? lit
  if (!products.length) return null
  if (products.length <= SHOWN) return <>{products.map((product) => <ProductCard key={product.id} product={product} onOpen={onOpen} />)}</>
  const names = products.slice(0, 3).map((product) => product.name).join(' · ')
  return (
    <section className="product-list" aria-label="Products named in the answer">
      <button className="pl-head" onClick={() => setChosen(!open)} aria-expanded={open}>
        <Icon name="queue" size={15} />
        <span className="pl-title">{products.length} products</span>
        <span className="pl-names">{names}</span>
        <span className="tl-chev" data-open={open}>
          <Icon name="chevron" size={16} />
        </span>
      </button>
      <Fold open={open}>
        <div className="pl-body">
          {products.map((product) => (
            <ProductCard key={product.id} product={product} onOpen={onOpen} />
          ))}
        </div>
      </Fold>
    </section>
  )
}
