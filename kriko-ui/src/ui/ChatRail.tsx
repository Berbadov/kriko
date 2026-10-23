import { useEffect } from 'react'
import { useFocus } from '../chat/focus'
import { pageKey, productKey, type Group } from '../chat/view'
import type { Product, SourcePage } from '../activity/run'
import { useProductActions } from '../engine/products'
import { siteHost } from '../engine/favicons'
import { SiteMark } from './ClaimChip'
import { ExternalLink } from './ExternalLink'
import { Icon } from './Icon'
import { PixelGlyph } from './PixelGlyph'

const READ_WORD: Record<SourcePage['read'], string> = { read: 'Read', failed: 'Could not be read', listed: 'Named in the answer' }

/** Every product and every source page the conversation has touched, newest
 *  turn on top. It draws what the turns already carry; it keeps nothing of its
 *  own. A source row leads with the site's own icon, which the engine fetches
 *  (`GET /api/favicon`); the letter under it is the host's, so the row has a
 *  mark while the engine answers and when it has no icon to give. Rows are
 *  keyed by what they are (a product, a page address), so a poll that adds a
 *  row does not make the others enter again. */
export function ChatRail({
  groups,
  onOpen,
  open,
  onClose,
}: {
  groups: Group[]
  onOpen: (lookupId: string) => void
  /** In a narrow window the column is a drawer: whether it is drawn. */
  open: boolean
  onClose: () => void
}) {
  // Escape closes the drawer a narrow window shows; in a wide one nothing is open to close.
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])
  const products = groups.reduce((total, group) => total + group.products.length, 0)
  const pages = groups.reduce((total, group) => total + group.pages.length, 0)
  return (
    <aside id="chat-rail" className="chat-rail" data-open={open} aria-label="Sources and products">
      <header className="cr-head">
        <h2>Sources and products</h2>
        <span className="mono muted">
          {products} {products === 1 ? 'product' : 'products'} · {pages} {pages === 1 ? 'page' : 'pages'}
        </span>
        <button className="icon-btn sm cr-close" onClick={onClose} aria-label="Close the sources panel">
          <Icon name="x" size={14} />
        </button>
      </header>
      <div className="chat-rail-scroll">
        {groups.length === 0 && <p className="cr-empty">Products an answer names and pages it reads collect here as the conversation runs.</p>}
        {groups.map((group) => (
          <section key={group.id} className="cr-group" aria-label={`Question ${group.n}`}>
            <h3 title={group.prompt}>
              <span className="mono">{group.n}</span>
              <span className="cr-prompt">{group.prompt}</span>
            </h3>
            {group.running && group.products.length === 0 && group.pages.length === 0 && (
              <p className="cr-working">
                <PixelGlyph size={12} active />
                Reading
              </p>
            )}
            <ul>
              {group.products.map((product) => (
                <RailProduct key={productKey(product.id)} product={product} onOpen={onOpen} />
              ))}
              {group.pages.map((page) => (
                <RailPage key={pageKey(page.url)} page={page} />
              ))}
            </ul>
          </section>
        ))}
      </div>
    </aside>
  )
}

function RailProduct({ product, onOpen }: { product: Product; onOpen: (lookupId: string) => void }) {
  const focus = useFocus()
  const key = productKey(product.id)
  const { opening, open } = useProductActions(product)
  return (
    <li className="cr-item" data-kind="product" data-focus-key={key} data-lit={focus.key === key || undefined}>
      <button className="cr-main" onClick={() => focus.select(key, 'rail')} aria-pressed={focus.key === key}>
        <strong>{product.name}</strong>
        <span className="mono muted">{product.note}</span>
      </button>
      <div className="cr-actions">
        <button className="btn" onClick={() => void open(onOpen)} disabled={opening.step === 'busy'}>
          {opening.step === 'busy' ? <PixelGlyph size={13} active /> : null}
          Open check
        </button>
        {opening.step === 'failed' && (
          <span className="error-line" role="alert">
            {opening.note}
          </span>
        )}
      </div>
    </li>
  )
}

function RailPage({ page }: { page: SourcePage }) {
  const focus = useFocus()
  const key = pageKey(page.url)
  const host = siteHost(page.host, page.url)
  return (
    <li className="cr-item" data-kind="page" data-focus-key={key} data-lit={focus.key === key || undefined} data-read={page.read}>
      <button className="cr-main" onClick={() => focus.select(key, 'rail')} aria-pressed={focus.key === key}>
        <span className="cr-title">
          {host && <SiteMark host={host} />}
          <strong>{page.title || page.host || page.url}</strong>
        </span>
        <span className="cr-meta">
          {page.title && page.host && <span className="mono muted">{page.host}</span>}
          {page.tier ? (
            <span className="cr-tier" data-standing={page.standing ?? 'neutral'} title="The kind of site, as Kriko classifies it">
              {page.tier}
            </span>
          ) : (
            <span className="cr-tier" data-standing="none" title="Kriko has not classified this site">
              not classified
            </span>
          )}
          <span className="muted cr-read">{READ_WORD[page.read]}{page.cited && page.read !== 'listed' ? ' · cited' : ''}</span>
        </span>
      </button>
      <div className="cr-actions">
        <ExternalLink className="cr-link" href={page.url}>
          Open the page
          <Icon name="external" size={13} />
        </ExternalLink>
      </div>
    </li>
  )
}
