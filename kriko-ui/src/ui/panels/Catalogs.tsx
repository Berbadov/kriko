import { Disclosure } from '../Disclosure'
import { Icon } from '../Icon'
import { Textarea } from '../../arc/textarea/textarea'
import { useCallback, useEffect, useRef, useState } from 'react'
import { engineUrl, get, inShell, post, uploadArtifact, seg } from '../../engine/api'
import { followJob } from '../../engine/jobs'
import { useEngine } from '../../engine/Engine'
import { useCatalogs, type Catalog, type Draft } from '../../engine/catalogs'
import { sharedPacks, type SharedPack } from '../../engine/harvest'
import { useMarks, type Mark } from '../../engine/marks'
import { findProduct, useProcurement } from '../../engine/procurement'
import { ago, askAgentToCategorizeLook, assignSavedLook, useSavedLooks } from '../../engine/history'
import type { SavedCatalog, SavedLook } from '../../engine/looks'
import { Select } from '../controls'

/** Products listed per page; a catalog can hold more than the reader scrolls past. */
const PAGE = 50

const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

/** The engine's closed verdict vocabulary, written as words. `wrong` and
 *  `useful` are already words; the third is the only one with an underscore,
 *  and the engine's `verdicts` list is the only place the set comes from. */
const verdictWord = (verdict: string) => verdict.replaceAll('_', ' ')

const reason = (error: unknown, fallback: string) => (error instanceof Error ? error.message : fallback)

/** One catalog's line in the published index, or in the engine's view of an installed one. */
interface IndexRow {
  pack_id: string
  name: string
  installed_version: string
  offered_version: string
  /** `available` (installed, newer offered), `up_to_date`, `not_installed`, or `unknown` / `refused`. */
  state: string
}

/** A product of a catalog, as `/api/subjects` and `/api/subjects/search` name it. */
interface Product {
  subject_id: string
  pack_id: string
  label: string
  claims: number
}

interface ProductPage {
  items: Product[]
  total: number
}

/** One catalog's product list, tagged with the catalog it was read for. */
interface Listing {
  pack: string
  items: Product[]
  total: number
  loaded: boolean
  problem: string
}

const EMPTY_LISTING: Listing = { pack: '', items: [], total: 0, loaded: false, problem: '' }

const listingPath = (pack: string, q: string, offset: number) =>
  `/api/subjects?pack_id=${encodeURIComponent(pack)}&paged=true&limit=${PAGE}&offset=${offset}${q ? `&q=${encodeURIComponent(q)}` : ''}`

// Demo data: what `?demo` shows with no engine. Not read by any engine logic.
const DEMO_INDEX: IndexRow[] = [
  { pack_id: 'air.purifier', name: 'Air purifiers', installed_version: '0.2.0', offered_version: '0.3.0', state: 'available' },
  { pack_id: 'kettles', name: 'Kettles', installed_version: '0.1.0', offered_version: '0.1.0', state: 'up_to_date' },
  { pack_id: 'headphones', name: 'Headphones', installed_version: '0.1.0', offered_version: '0.1.0', state: 'up_to_date' },
  { pack_id: 'stick.blenders', name: 'Stick blenders', installed_version: '', offered_version: '0.2.0', state: 'not_installed' },
]
const DEMO_PRODUCTS: Record<string, (Product & { lead: string })[]> = {
  'air.purifier': [
    { subject_id: 'demo-air-1', pack_id: 'air.purifier', label: 'Compact 300 purifier', claims: 6, lead: 'The filter is sold separately and its price is not on the listing' },
    { subject_id: 'demo-air-2', pack_id: 'air.purifier', label: 'Tower 500 purifier', claims: 3, lead: 'Fan noise on the highest setting is reported' },
    { subject_id: 'demo-air-3', pack_id: 'air.purifier', label: 'Mini desk purifier', claims: 0, lead: '' },
  ],
  kettles: [
    { subject_id: 'demo-kettle-1', pack_id: 'kettles', label: 'Glass 1.7 kettle', claims: 4, lead: 'The base can overheat when left on the stand' },
    { subject_id: 'demo-kettle-2', pack_id: 'kettles', label: 'Steel 1.5 kettle', claims: 2, lead: 'The lid hinge is reported to loosen after a year' },
  ],
  headphones: [
    { subject_id: 'demo-head-1', pack_id: 'headphones', label: 'Over-ear 700', claims: 5, lead: 'Battery capacity falls quickly under daily use' },
  ],
}
const DEMO_LEADS: Record<string, string> = Object.fromEntries(Object.values(DEMO_PRODUCTS).flat().map((row) => [row.subject_id, row.lead]))
const demoListing = (pack: string, q: string): Product[] =>
  (DEMO_PRODUCTS[pack] ?? []).filter((row) => !q || row.label.toLowerCase().includes(q.toLowerCase()))
const demoSearch = (q: string): Product[] =>
  Object.values(DEMO_PRODUCTS).flat().filter((row) => row.label.toLowerCase().includes(q.toLowerCase()))

/** What the window already read of each product's leading finding, and when. `null` means the
 *  read failed, which is not the same as having no finding. Kept a minute, so going back to a
 *  list does not read every product again. */
const LEAD_KEEP_MS = 60_000
/** Reads of a product's finding that may be on their way at once. */
const LEAD_PARALLEL = 6
const leadCache = new Map<string, { at: number; lead: string | null }>()

/**
 * The leading finding of each product, read only for the rows that are on screen
 * (a row calls `want` when it scrolls into view), at most six at a time, and kept.
 * A catalog of hundreds of products used to ask the engine about every one of them
 * the moment the list opened.
 */
function useLeads(live: boolean): { leads: Record<string, string | null>; want: (id: string) => void } {
  const [leads, setLeads] = useState<Record<string, string | null>>({})
  const queue = useRef<string[]>([])
  const asked = useRef(new Set<string>())
  const flying = useRef(0)
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => { alive.current = false }
  }, [])

  const pump = useCallback(function pump() {
    while (flying.current < LEAD_PARALLEL && queue.current.length) {
      const id = queue.current.shift()!
      flying.current += 1
      void get<{ claims?: { title?: string }[] }>(`/api/subjects/${seg(id)}`)
        .then((found) => found.claims?.[0]?.title || '', () => null)
        .then((lead) => {
          leadCache.set(id, { at: Date.now(), lead })
          if (alive.current) setLeads((now) => ({ ...now, [id]: lead }))
        })
        .finally(() => {
          flying.current -= 1
          pump()
        })
    }
  }, [])

  const want = useCallback((id: string) => {
    if (!live || asked.current.has(id)) return
    asked.current.add(id)
    const kept = leadCache.get(id)
    if (kept && Date.now() - kept.at < LEAD_KEEP_MS) {
      setLeads((now) => ({ ...now, [id]: kept.lead }))
      return
    }
    queue.current.push(id)
    pump()
  }, [live, pump])
  return { leads, want }
}

const leadText = (lead: string | null | undefined) => (lead === undefined ? 'Reading the finding…' : lead === null ? '' : lead || 'No sourced risk yet')

/** What Kriko knows. Each catalog is one kind of product; a product opens its saved check. */
export function CatalogsPanel({ onOpen }: { onOpen?: (lookupId: string) => void }) {
  const { catalogs, drafts, problem, busy, setEnabled, stepBack, install, discard, reload } = useCatalogs()
  const [asking, setAsking] = useState<string | null>(null)
  const { mode, preferred } = useEngine()
  const { estimates } = useProcurement()
  const [status, setStatus] = useState('')
  const [working, setWorking] = useState(false)
  const [checking, setChecking] = useState(false)
  const [category, setCategory] = useState('')
  const [index, setIndex] = useState<IndexRow[]>([])
  const [indexProblem, setIndexProblem] = useState('')
  /** The catalogs the last harvest said gained a claim, with the `.kpack` path
   *  the job itself sent (`tasks.pack_harvest`). Cleared when another job starts
   *  so an old link is never shown as this run's. */
  const [shared, setShared] = useState<SharedPack[]>([])
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<Product[]>([])
  const [hitsProblem, setHitsProblem] = useState('')
  /** The catalog whose product list is open; empty when the overview is shown. */
  const [browsing, setBrowsing] = useState('')
  const [filter, setFilter] = useState('')
  const [listing, setListing] = useState<Listing>(EMPTY_LISTING)
  const [opening, setOpening] = useState('')
  const [openProblem, setOpenProblem] = useState('')
  const input = useRef<HTMLInputElement>(null)
  const live = mode === 'live'
  // The reader's own marks, read from the engine. `null` means "not this
  // window's to draw" (demo has no engine), which is not an empty list.
  const marks = useMarks()
  const saved = useSavedLooks()
  const offered = live ? index : DEMO_INDEX

  /** The index the engine answers with: the published catalogs, and each installed one's state. */
  const applyIndex = useCallback((found: { packs?: IndexRow[]; error?: string | null }) => {
    setIndexProblem(found.error ?? '')
    setIndex(found.packs ?? [])
    return found
  }, [])

  const checkIndex = useCallback(async (fresh: boolean) => {
    setChecking(true)
    try {
      const found = applyIndex(await get<{ packs: IndexRow[]; error?: string | null }>(`/api/packs/updates${fresh ? '?fresh=true' : ''}`, 30000))
      if (fresh) setStatus(found.error ? found.error : (found.packs ?? []).some((row) => row.state === 'not_installed') ? 'Release catalogs loaded.' : 'No release catalogs are available.')
    } catch (error) {
      setIndexProblem(reason(error, 'Could not load catalogs.'))
    } finally {
      setChecking(false)
    }
  }, [applyIndex])

  // The published index is read once when the page opens; the engine answers from its own cache.
  useEffect(() => {
    if (!live) return
    let on = true
    void get<{ packs: IndexRow[]; error?: string | null }>('/api/packs/updates', 30000)
      .then((found) => { if (on) applyIndex(found) })
      .catch((error: unknown) => { if (on) setIndexProblem(reason(error, 'Could not load catalogs.')) })
    return () => {
      on = false
    }
  }, [live, applyIndex])

  const job = async (path: string, body: object) => {
    setWorking(true)
    setStatus('Starting…')
    setShared([])
    try {
      const sent = await post<{job_id: string}>(path, body)
      const ended = await followJob(sent.job_id, (reading) => setStatus(reading.message || 'Working…'))
      if (ended?.state !== 'succeeded') throw new Error(ended?.message || 'The operation did not finish.')
      setStatus(ended.message || 'Finished')
      // Only a harvest result carries `packs`; every other job shares nothing.
      setShared(sharedPacks(ended.result))
      await reload()
      // A harvest files what it can decide; the looks it could not are the
      // section below, so it is re-read with the catalogs it may have changed.
      await saved.reload()
      await checkIndex(false)
    } catch (error) { setStatus(error instanceof Error ? error.message : 'The operation failed. Try again.') }
    finally { setWorking(false) }
  }

  const importFile = async (file?: File) => {
    if (!file) return
    setWorking(true)
    try { await uploadArtifact('/api/packs/import', file); await reload(); setStatus('Catalog installed.') }
    catch (error) { setStatus(error instanceof Error ? error.message : 'The catalog could not be installed.') }
    finally { setWorking(false); if (input.current) input.current.value = '' }
  }

  // Global search: product matches come from the engine once two letters are typed.
  // The effect only fetches; what is shown is derived from the query during render.
  useEffect(() => {
    const typed = query.trim()
    if (!live || typed.length < 2) return
    let on = true
    const timer = window.setTimeout(async () => {
      try {
        // `/api/search`, not `/api/subjects/search`: the subjects route shadows that path.
        const data = await get<{ items: Product[] }>(`/api/search?q=${encodeURIComponent(typed)}&limit=20`)
        if (on) { setHits(data.items ?? []); setHitsProblem('') }
      } catch (error) {
        if (on) setHitsProblem(reason(error, 'Search did not answer.'))
      }
    }, 250)
    return () => {
      on = false
      window.clearTimeout(timer)
    }
  }, [query, live])

  // The product list of the open catalog. Each list is tagged with the catalog it
  // belongs to, so a list from the catalog before never reads as the one now open.
  useEffect(() => {
    if (!browsing || !live) return
    const typed = filter.trim()
    let on = true
    const timer = window.setTimeout(async () => {
      try {
        const data = await get<ProductPage>(listingPath(browsing, typed, 0))
        if (on) setListing({ pack: browsing, items: data.items ?? [], total: data.total ?? 0, loaded: true, problem: '' })
      } catch (error) {
        if (on) setListing({ pack: browsing, items: [], total: 0, loaded: true, problem: reason(error, 'Could not read this catalog.') })
      }
    }, typed ? 250 : 0)
    return () => {
      on = false
      window.clearTimeout(timer)
    }
  }, [browsing, filter, live])

  const typedFilter = filter.trim()
  const listed: Listing = !browsing
    ? EMPTY_LISTING
    : live
      ? listing.pack === browsing ? listing : EMPTY_LISTING
      : { pack: browsing, items: demoListing(browsing, typedFilter), total: demoListing(browsing, typedFilter).length, loaded: true, problem: '' }
  const { leads, want } = useLeads(live)
  const leadOf = (id: string) => (live ? leads[id] : DEMO_LEADS[id])

  const more = async () => {
    setListing((now) => ({ ...now, problem: '' }))
    try {
      const data = await get<ProductPage>(listingPath(browsing, typedFilter, listed.items.length))
      setListing((now) => ({ ...now, items: [...now.items, ...(data.items ?? [])], total: data.total ?? now.total }))
    } catch (error) {
      setListing((now) => ({ ...now, problem: reason(error, 'Could not read more products.') }))
    }
  }

  /** Save the product's check, then open it. The engine keeps one saved check per product. */
  const openProduct = async (subjectId: string, label: string) => {
    setOpening(subjectId)
    setOpenProblem('')
    try {
      let lookup = `demo:${label}`
      if (live) {
        const checked = await post<{ lookup_id?: string }>(`/api/products/${seg(subjectId)}/check`, {})
        if (!checked.lookup_id) throw new Error('The answer was not saved.')
        lookup = checked.lookup_id
      }
      onOpen?.(lookup)
    } catch (error) {
      setOpenProblem(reason(error, 'The engine does not answer.'))
    } finally {
      setOpening('')
    }
  }

  // A failed read is not a wait. `{problem || 'Reading the catalogs…'}` rendered
  // both in the muted note style, so a refusal looked like a slow screen.
  if (!catalogs && problem) {
    return (
      <aside className="k-notice" data-tone="risk" role="alert">
        Your catalogs could not be read. {problem}
      </aside>
    )
  }
  if (!catalogs) return <p className="library-note">Reading the catalogs…</p>

  const waiting = drafts.filter((row) => !row.installed)
  const packIds = new Set(catalogs.map((row) => row.id))
  const orphans = (marks.marks ?? []).filter((mark) => !packIds.has(mark.pack_id))
  // A saved look the engine did not file is the one that gets the choice. Both
  // category routes refuse a look that has not finished (`_quicklook_job`), so
  // a running or failed one is not offered here. An abstention is never drawn
  // as a catalog: `assignedTo` is empty and the engine's `openQuestion` says
  // why.
  const unfiled = (saved.looks ?? []).filter((look) => look.jobId && look.status === 'succeeded' && !look.assignedTo)
  const marked = marks.verdicts.reduce((total, verdict) => total + (marks.counts[verdict] ?? 0), 0)
  const breakdown = marks.verdicts.map((verdict) => `${marks.counts[verdict] ?? 0} ${verdictWord(verdict)}`).join(' · ')

  const needle = query.trim().toLowerCase()
  const nameOf = (packId: string) => catalogs.find((row) => row.id === packId)?.name ?? packId
  const matchedCatalogs = needle ? catalogs.filter((row) => row.name.toLowerCase().includes(needle)) : []
  const matchedProducts = needle.length >= 2 ? (live ? hits : demoSearch(needle)) : []
  const installable = offered.filter((row) => row.state === 'not_installed')
  const stateOf = (packId: string) => offered.find((row) => row.pack_id === packId)?.state ?? ''
  const browse = catalogs.find((row) => row.id === browsing)
  const estimated = (subjectId: string) => findProduct(estimates, subjectId).length > 0

  return (
    <>
      <label className="library-search">
        <Icon name="search" size={16} />
        <input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search catalogs and products"
          aria-label="Search catalogs and products"
        />
      </label>
      {problem && <aside className="k-notice" data-tone="risk" role="alert">{problem}</aside>}

      {needle && (
        <>
          <section className="k-group" aria-labelledby="catalogs-found-catalogs">
            <h3 className="k-caption" id="catalogs-found-catalogs">Catalogs</h3>
            {matchedCatalogs.length > 0 ? (
              <ul className="k-card k-list">
                {matchedCatalogs.map((row) => (
                  <li key={row.id}>
                    <button className="k-row" onClick={() => setBrowsing(row.id)}>
                      <span className="k-row-icon" aria-hidden="true"><Icon name="book" size={16} /></span>
                      <span className="k-row-main">
                        <span className="k-row-title">{row.name}</span>
                        <span className="k-row-note">{[count(row.products, 'product', 'products'), count(row.risks, 'risk', 'risks')].join(' · ')}</span>
                      </span>
                      <span className="library-word">Open</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="library-note">No installed catalog has that name.</p>
            )}
          </section>
          {needle.length >= 2 && (
            <section className="k-group" aria-labelledby="catalogs-found-products">
              <h3 className="k-caption" id="catalogs-found-products">Products</h3>
              {hitsProblem && <aside className="k-notice" data-tone="risk" role="alert">{hitsProblem}</aside>}
              {matchedProducts.length > 0 ? (
                <ul className="k-card k-list">
                  {matchedProducts.map((row) => (
                    <ProductRow
                      key={row.subject_id}
                      product={row}
                      note={nameOf(row.pack_id)}
                      estimated={estimated(row.subject_id)}
                      busy={opening === row.subject_id}
                      onOpen={() => void openProduct(row.subject_id, row.label)}
                    />
                  ))}
                </ul>
              ) : (
                <p className="library-note">No product matches “{query.trim()}”.</p>
              )}
            </section>
          )}
        </>
      )}

      {!needle && browse && (
        <>
          <div className="library-bar">
            <button className="k-btn" data-kind="quiet" data-size="sm" onClick={() => setBrowsing('')}>All catalogs</button>
          </div>
          <section className="k-group" aria-labelledby="catalogs-browse">
            <div className="library-browse-head">
              <h3 className="library-browse-title" id="catalogs-browse">{browse.name}</h3>
              <p className="library-note">{`v${browse.version} · ${count(browse.products, 'product', 'products')} · ${count(browse.risks, 'risk', 'risks')}`}</p>
            </div>
            <label className="library-search">
              <Icon name="search" size={16} />
              <input
                type="search"
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                placeholder={`Filter products in ${browse.name}`}
                aria-label={`Filter products in ${browse.name}`}
              />
            </label>
            {listed.problem && <aside className="k-notice" data-tone="risk" role="alert">{listed.problem}</aside>}
            {openProblem && <aside className="k-notice" data-tone="risk" role="alert">{openProblem}</aside>}
            {listed.loaded && listed.items.length === 0 && (
              <p className="library-note">{filter.trim() ? 'No product in this catalog matches.' : 'This catalog has no products yet.'}</p>
            )}
            {listed.items.length > 0 && (
              <ul className="k-card k-list" aria-label={`Products in ${browse.name}`}>
                {listed.items.map((row) => (
                  <ProductRow
                    key={row.subject_id}
                    product={row}
                    lead={leadOf(row.subject_id)}
                    onSeen={() => want(row.subject_id)}
                    estimated={estimated(row.subject_id)}
                    busy={opening === row.subject_id}
                    onOpen={() => void openProduct(row.subject_id, row.label)}
                  />
                ))}
              </ul>
            )}
            {listed.items.length < listed.total && (
              <div className="library-actions">
                <button className="k-btn" data-kind="quiet" data-size="sm" onClick={() => void more()}>
                  {`Show ${Math.min(PAGE, listed.total - listed.items.length)} more`}
                </button>
              </div>
            )}
          </section>
        </>
      )}

      {!needle && !browse && (
        <>
          <section className="k-group" aria-labelledby="catalogs-installed">
            <h3 className="k-caption" id="catalogs-installed">Installed</h3>
            {marks.problem && (
              <aside className="k-notice" data-tone="risk" role="alert">
                Your marks could not be read. {marks.problem}{' '}
                <button className="k-btn" data-size="sm" onClick={() => void marks.reload()}>Try again</button>
              </aside>
            )}
            {marks.marks && (
              <p className="library-note mark-summary">
                {marked > 0
                  ? `You marked ${count(marked, 'claim', 'claims')}${breakdown ? `: ${breakdown}` : ''}.`
                  : 'No claim is marked yet. A mark you add from a result page is kept here.'}
              </p>
            )}
            {catalogs.length === 0 ? (
              <div className="k-empty catalogs-empty">
                <strong>No catalogs yet</strong>
                <p>Kriko still checks a product from what it finds on the page. A catalog adds what is known about one kind of product.</p>
                <button
                  className="k-btn"
                  data-kind="primary"
                  disabled={!installable.length}
                  onClick={() => document.getElementById('catalogs-available')?.scrollIntoView({ behavior: 'smooth', block: 'start' })}
                >
                  Install a catalog
                </button>
              </div>
            ) : (
              <ul className="k-card k-list catalogs-installed">
                {catalogs.map((row) => (
                  <CatalogRow
                    key={row.id}
                    row={row}
                    update={stateOf(row.id)}
                    working={busy === row.id || working}
                    asking={asking === `back:${row.id}`}
                    marks={(marks.marks ?? []).filter((mark) => mark.pack_id === row.id)}
                    onBrowse={() => setBrowsing(row.id)}
                    onUpdate={() => void job('/api/packs/update', { pack_id: row.id })}
                    onToggle={(on) => void setEnabled(row.id, on)}
                    onAsk={() => setAsking(`back:${row.id}`)}
                    onKeep={() => setAsking(null)}
                    onBack={() => {
                      setAsking(null)
                      void stepBack(row.id)
                    }}
                  />
                ))}
              </ul>
            )}
          </section>

          <section className="k-group" id="catalogs-available" aria-labelledby="catalogs-available-caption">
            <h3 className="k-caption" id="catalogs-available-caption">Available to install</h3>
            <ul className="k-card k-list">
              {installable.length === 0 && (
                <li className="k-row">
                  <span className="k-row-main">
                    <span className="k-row-note">
                      {indexProblem ? 'The catalog index could not be reached.' : live ? 'No new catalog is offered. Check again to look.' : 'No catalog to install in this window.'}
                    </span>
                  </span>
                </li>
              )}
              {installable.map((row) => (
                <li className="k-row" key={row.pack_id}>
                  <span className="k-row-icon" aria-hidden="true"><Icon name="plus" size={16} /></span>
                  <span className="k-row-main">
                    <span className="k-row-title">{row.name}</span>
                    <span className="k-row-note">{`v${row.offered_version}`}</span>
                  </span>
                  <span className="k-row-control">
                    <button
                      className="k-btn"
                      data-size="sm"
                      disabled={working || !live}
                      onClick={() => void job('/api/packs/update', { pack_id: row.pack_id })}
                    >
                      Install
                    </button>
                  </span>
                </li>
              ))}
            </ul>
            <div className="library-actions">
              <button className="k-btn" data-kind="quiet" data-size="sm" disabled={checking || !live} onClick={() => void checkIndex(true)}>
                {checking ? 'Checking…' : 'Check for new catalogs'}
              </button>
            </div>
            {indexProblem && <aside className="k-notice" data-tone="warn" role="status">{indexProblem}</aside>}
          </section>

          {waiting.length > 0 && (
            <section className="k-group" aria-labelledby="catalogs-drafts">
              <h3 className="k-caption" id="catalogs-drafts">Drafted for you</h3>
              <ul className="k-card k-list">
                {waiting.map((row) => (
                  <DraftRow
                    key={row.slug}
                    row={row}
                    working={busy === row.slug}
                    asking={asking === `drop:${row.slug}`}
                    onInstall={() => void install(row.slug)}
                    onAsk={() => setAsking(`drop:${row.slug}`)}
                    onKeep={() => setAsking(null)}
                    onDiscard={() => {
                      setAsking(null)
                      void discard(row.slug)
                    }}
                  />
                ))}
              </ul>
            </section>
          )}

          {/* Filing is not permission to invent an assignment: a saved look the
              engine could not classify keeps its open question and takes a catalog
              only from the reader's press. The candidates are the engine's own
              `categorization_catalogs`, the same list the route validates against. */}
          {saved.problem && (
            <aside className="k-notice" data-tone="risk" role="alert">
              Your saved Quick Looks could not be read. {saved.problem}{' '}
              <button className="k-btn" data-size="sm" onClick={() => void saved.reload()}>Try again</button>
            </aside>
          )}
          {unfiled.length > 0 && (
            <section className="k-group" aria-labelledby="catalogs-unfiled">
              <h3 className="k-caption" id="catalogs-unfiled">Quick looks with no catalog yet</h3>
              <ul className="k-card k-list">
                {unfiled.map((look) => (
                  <SavedLookRow key={look.id} look={look} catalogs={saved.catalogs} onSaved={() => void saved.reload()} />
                ))}
              </ul>
            </section>
          )}

          <section className="k-group" aria-labelledby="catalogs-share">
            <h3 className="k-caption" id="catalogs-share">Share and grow</h3>
            <div className="k-card k-list">
              <div className="k-row">
                <span className="k-row-main">
                  <span className="k-row-title">Update catalogs</span>
                  <span className="k-row-note">Fetch the newest version of each installed catalog.</span>
                </span>
                <span className="k-row-control">
                  <button className="k-btn" disabled={working || !live} onClick={() => void job('/api/packs/update', {})}>Update catalogs</button>
                </span>
              </div>
              <div className="k-row">
                <span className="k-row-main">
                  <span className="k-row-title">File saved Quick Looks</span>
                  <span className="k-row-note">File each finished check into the catalog that holds its product. No agent is used.</span>
                </span>
                <span className="k-row-control">
                  <button className="k-btn" disabled={working || !live} onClick={() => void job('/api/packs/harvest', {})}>File saved Quick Looks</button>
                </span>
              </div>
              <div className="k-row">
                <span className="k-row-main">
                  <span className="k-row-title">Install a catalog file</span>
                  <span className="k-row-note">Install a .kpack that someone shared with you.</span>
                </span>
                <span className="k-row-control">
                  <input ref={input} hidden type="file" accept=".kpack" onChange={(event) => void importFile(event.target.files?.[0])} />
                  <button className="k-btn" disabled={working || !live} onClick={() => input.current?.click()}>Import .kpack</button>
                </span>
              </div>
              <div className="k-row" data-stack>
                <span className="k-row-main">
                  <span className="k-row-title">Research a new catalog</span>
                  <span className="k-row-note">Describe the category and research you need. The selected agent drafts it, and you review the draft before installing.</span>
                </span>
                <Textarea label="Catalog to research" value={category} onChange={(event) => setCategory(event.target.value)} maxLength={500} rows={3} placeholder="For example: cordless drills sold in my market" />
                <span className="k-row-control">
                  <button className="k-btn" disabled={working || !live || !category.trim()} onClick={() => void job('/api/packs/author', { category, harness: preferred })}>Research draft</button>
                </span>
              </div>
              {(status || shared.length > 0) && (
                <div className="k-row" data-stack>
                  {status && <p role="status" className="library-note">{status}</p>}
                  {/* What a harvest produced is shareable: the job's own result names each
                      catalog that gained a claim and the engine path to its `.kpack`. The
                      path is joined to the base every call uses, never to a port — the
                      engine binds an OS-chosen one. The packaged window is not served by
                      the engine, so following the same path there would replace Kriko
                      with the shell's 404; the shell would have to hand the bytes over,
                      which `engine_request` cannot do (it reads a reply as text). */}
                  {shared.length > 0 && (
                    <ul className="library-share-list">
                      {shared.map((row) => (
                        <li key={row.slug || row.pack_id}>
                          <strong>{row.name || row.slug}</strong>
                          <small>
                            Installed here. <a
                              className="share-link"
                              href={engineUrl(row.artifact)}
                              onClick={(event) => {
                                if (inShell()) event.preventDefault()
                              }}
                            >{(row.slug || row.pack_id) + '.kpack'}</a> installs it on another computer.
                          </small>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          </section>

          {/* A mark snapshots its pack id and claim title, so a mark outlives the
              catalog it was made in. Dropping these would lose the reader's own
              notes the day they remove a catalog, which is the opposite of what
              `claim_marks` is for. */}
          {orphans.length > 0 && (
            <section className="k-group" aria-labelledby="catalogs-orphans">
              <h3 className="k-caption" id="catalogs-orphans">Marks from catalogs you no longer have</h3>
              <ul className="k-card k-list">
                {orphans.map((mark) => (
                  <li className="k-row" key={`${mark.pack_id}/${mark.claim_id}`}>
                    <span className="k-row-main">
                      <span className="k-row-title"><strong>{mark.title || mark.claim_id}</strong></span>
                      <span className="k-row-note">{`${verdictWord(mark.verdict)} · catalog ${mark.pack_id} · ${ago(mark.updated_at)}`}</span>
                      {mark.note && <span className="k-row-note mark-note">{mark.note}</span>}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </>
      )}
    </>
  )
}

/** One product in a list: its name, its leading finding (or the catalog it came from),
 *  the risk count, and the procurement tie-in when an estimate holds it. */
function ProductRow({
  product,
  lead,
  note,
  estimated,
  busy,
  onOpen,
  onSeen,
}: {
  product: Product
  /** Called once, when the row first scrolls into view. */
  onSeen?: () => void
  lead?: string | null
  note?: string
  estimated: boolean
  busy: boolean
  onOpen: () => void
}) {
  const row = useRef<HTMLLIElement>(null)
  useEffect(() => {
    const el = row.current
    if (!onSeen || !el) return
    if (typeof IntersectionObserver === 'undefined') {
      onSeen()
      return
    }
    const seen = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) {
        seen.disconnect()
        onSeen()
      }
    }, { rootMargin: '200px' })
    seen.observe(el)
    return () => seen.disconnect()
    // The callback only names the product; it is read once, when the row mounts.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return (
    <li ref={row}>
      <button className="k-row library-product" onClick={onOpen} disabled={busy} aria-busy={busy}>
        <span className="k-row-main">
          <span className="k-row-title">{product.label}</span>
          <span className="k-row-note">{busy ? 'Saving the check…' : note ?? leadText(lead)}</span>
        </span>
        {estimated && <span className="k-pill">In an estimate</span>}
        <span className="k-row-value">{count(product.claims, 'risk', 'risks')}</span>
        <span className="library-chevron" aria-hidden="true"><Icon name="chevron" size={16} /></span>
      </button>
    </li>
  )
}

/** One saved quick look the engine has not filed. Two presses, both the
 *  reader's: choose an installed catalog, or spend an agent to name one. */
function SavedLookRow({ look, catalogs, onSaved }: { look: SavedLook; catalogs: SavedCatalog[]; onSaved: () => void }) {
  const [pick, setPick] = useState('')
  const [working, setWorking] = useState(false)
  const [note, setNote] = useState('')
  const meta = [ago(look.createdAt), look.problems === 0 ? 'No sourced problems' : count(look.problems, 'sourced problem', 'sourced problems')].join(' · ')

  const file = async () => {
    setWorking(true)
    setNote('')
    try {
      const record = await assignSavedLook(look.jobId, pick)
      setNote(record.message || 'Filed.')
      onSaved()
    } catch (error) { setNote(reason(error, 'The catalog choice could not be saved.')) }
    finally { setWorking(false) }
  }

  const ask = async () => {
    setWorking(true)
    setNote('Starting…')
    try {
      const started = await askAgentToCategorizeLook(look.jobId)
      const ended = await followJob(started.job_id, (reading) => setNote(reading.message || 'Working…'))
      if (ended?.state !== 'succeeded') throw new Error(ended?.message || 'The agent did not finish.')
      setNote(ended.message || 'Finished')
      onSaved()
    } catch (error) { setNote(reason(error, 'The agent could not classify it.')) }
    finally { setWorking(false) }
  }

  return (
    <li className="k-row" data-stack aria-busy={working}>
      <span className="k-row-main">
        <span className="k-row-title">{look.name || 'Quick look'}</span>
        <span className="k-row-note">{meta}</span>
        {look.openQuestion && <small className="look-question">{look.openQuestion}</small>}
        <span className="look-choose">
          <Select
            label={`Catalog for ${look.name || 'this quick look'}`}
            value={pick}
            onChange={setPick}
            options={[{ value: '', label: 'Choose a catalog' }, ...catalogs.map((row) => ({ value: row.pack_id, label: row.name }))]}
          />
          <button className="k-btn" data-size="sm" disabled={working || !pick} onClick={() => void file()}>Use this catalog</button>
          <button className="k-btn" data-size="sm" data-kind="quiet" disabled={working} onClick={() => void ask()}>Ask the agent to name it</button>
        </span>
        {note && <small className="look-note" role="status">{note}</small>}
      </span>
    </li>
  )
}

function CatalogRow({
  row,
  update,
  working,
  asking,
  marks,
  onBrowse,
  onUpdate,
  onToggle,
  onAsk,
  onKeep,
  onBack,
}: {
  row: Catalog
  /** The engine's verdict on the installed version: `available`, `up_to_date`, or empty when not checked. */
  update: string
  working: boolean
  asking: boolean
  marks: Mark[]
  onBrowse: () => void
  onUpdate: () => void
  onToggle: (on: boolean) => void
  onAsk: () => void
  onKeep: () => void
  onBack: () => void
}) {
  const meta = [`v${row.version}`, count(row.products, 'product', 'products'), count(row.risks, 'risk', 'risks'), row.enabled ? '' : 'Off']
    .filter(Boolean)
    .join(' · ')
  return (
    <li className="k-row catalogs-row" data-asking={asking} data-off={!row.enabled} aria-busy={working}>
      <span className="k-row-icon" aria-hidden="true"><Icon name="book" size={16} /></span>
      <span className="k-row-main">
        <span className="k-row-title">
          {row.name}
          {update === 'available' && <span className="k-pill" data-tone="warn">Update available</span>}
          {update === 'up_to_date' && <span className="k-pill" data-tone="ok">Up to date</span>}
        </span>
        <span className="k-row-note">{meta}</span>
        {/* What the reader said about this catalog's claims, where the
            catalog's own counts are already drawn. These are the engine's
            rows: the verdict, and the title and note it snapshotted. */}
        {marks.length > 0 && (
          <span className="mark-list">
            {marks.map((mark) => (
              <span className="mark-row" data-verdict={mark.verdict} key={mark.claim_id}>
                <span className="mark-verdict">{verdictWord(mark.verdict)}</span>
                <span className="mark-title">{mark.title || mark.claim_id}</span>
                {mark.note && <small className="mark-note">{mark.note}</small>}
              </span>
            ))}
          </span>
        )}
        {row.previous && !asking && (
          <span className="library-actions">
            <button className="k-btn" data-size="sm" data-kind="quiet" onClick={onAsk} disabled={working}>
              {`Go back to v${row.previous}`}
            </button>
          </span>
        )}
        {asking && (
          <span className="library-ask">
            <span>Go back?</span>
            <button className="k-btn" data-size="sm" onClick={onBack}>Go back</button>
            <button className="k-btn" data-size="sm" data-kind="quiet" onClick={onKeep}>Keep</button>
          </span>
        )}
      </span>
      <span className="k-row-control">
        <button className="k-btn" data-size="sm" onClick={onBrowse}>Open</button>
        {update === 'available' && (
          <button className="k-btn" data-size="sm" disabled={working} onClick={onUpdate}>Update</button>
        )}
        <button className="k-btn" data-size="sm" data-kind="quiet" disabled={working} onClick={() => onToggle(!row.enabled)}>
          {row.enabled ? 'Turn off' : 'Turn on'}
        </button>
      </span>
    </li>
  )
}

function DraftRow({
  row,
  working,
  asking,
  onInstall,
  onAsk,
  onKeep,
  onDiscard,
}: {
  row: Draft
  working: boolean
  asking: boolean
  onInstall: () => void
  onAsk: () => void
  onKeep: () => void
  onDiscard: () => void
}) {
  const [preview, setPreview] = useState<{ subjects: string[]; claims: number; principle: string; uncovered: unknown[] } | null>(null)
  const [previewProblem, setPreviewProblem] = useState('')
  const inspect = async () => {
    try { setPreview(await get(`/api/packs/drafts/${seg(row.slug)}`)); setPreviewProblem('') }
    catch (error) { setPreviewProblem(error instanceof Error ? error.message : 'Could not read this draft.') }
  }
  return (
    <li className="k-row" data-stack data-asking={asking} aria-busy={working}>
      <span className="k-row-main">
        <span className="k-row-title">{row.name}</span>
        <span className="k-row-note">{row.error || (row.version ? `v${row.version}` : 'Draft')}</span>
        {previewProblem && <span className="error-note" role="alert">{previewProblem}</span>}
        {preview && <Disclosure open title={`${preview.subjects.length} products · ${preview.claims} sourced problems`}><p>{preview.principle}</p><ul>{preview.subjects.map((name) => <li key={name}>{name}</li>)}</ul>{preview.uncovered.length > 0 && <p>{preview.uncovered.length} coverage gaps remain.</p>}</Disclosure>}
      </span>
      <span className="k-row-control">
        {asking ? (
          <>
            <span className="library-ask">Discard?</span>
            <button className="k-btn" data-size="sm" data-kind="danger" onClick={onDiscard}>Discard</button>
            <button className="k-btn" data-size="sm" data-kind="quiet" onClick={onKeep}>Keep</button>
          </>
        ) : (
          <>
            <button className="k-btn" data-size="sm" data-kind="quiet" onClick={() => void inspect()}>Review draft</button>
            {!row.error && (
              <button className="k-btn" data-size="sm" onClick={onInstall} disabled={working}>
                {working ? 'Installing…' : 'Install'}
              </button>
            )}
            <button className="k-btn" data-size="sm" data-kind="quiet" onClick={onAsk} disabled={working}>Discard</button>
          </>
        )}
      </span>
    </li>
  )
}
