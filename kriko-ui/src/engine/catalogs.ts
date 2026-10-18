import { useCallback, useEffect, useRef, useState } from 'react'
import { del, get, post, seg } from './api'
import { useEngine } from './Engine'

/** The catalogs that Kriko reads, and the drafts that an agent wrote for the reader.
 *  Live, these are `/api/packs`. A catalog is what Kriko knows about one kind of product.
 *  In demo mode the same shapes are kept in the window. */

export interface Catalog {
  id: string
  name: string
  version: string
  /** The version that a step back returns to. Empty when none is kept. */
  previous: string
  enabled: boolean
  products: number
  risks: number
  sources: number
}

export interface Draft {
  slug: string
  name: string
  version: string
  /** Set when the draft does not load. */
  error: string
  /** The catalog id when the draft is already installed. */
  installed: string
}

interface ApiPack {
  pack_id: string
  name: string
  version: string
  previous_version: string
  enabled: boolean
  subjects: number
  claims: number
  evidence: number
}

interface ApiDraft {
  slug: string
  name?: string
  version?: string
  error?: string
  installed_as?: string
}

const DEMO: Catalog[] = [
  { id: 'air.purifier', name: 'Air purifiers', version: '0.2.0', previous: '0.1.0', enabled: true, products: 12, risks: 41, sources: 88 },
  { id: 'kettles', name: 'Kettles', version: '0.1.0', previous: '', enabled: true, products: 7, risks: 19, sources: 33 },
  { id: 'headphones', name: 'Headphones', version: '0.1.0', previous: '', enabled: false, products: 9, risks: 24, sources: 0 },
]
const DEMO_DRAFTS: Draft[] = [
  { slug: 'robot-vacuums', name: 'Robot vacuums', version: '0.1.0', error: '', installed: '' },
  { slug: 'broken-draft', name: 'Broken draft', version: '', error: 'The draft has no products.', installed: '' },
]

const tidy = (row: ApiPack): Catalog => ({
  id: row.pack_id,
  name: row.name,
  version: row.version,
  previous: row.previous_version,
  enabled: row.enabled,
  products: row.subjects,
  risks: row.claims,
  sources: row.evidence,
})

export function useCatalogs() {
  const { mode } = useEngine()
  const [catalogs, setCatalogs] = useState<Catalog[] | null>(null)
  const [drafts, setDrafts] = useState<Draft[]>([])
  const [problem, setProblem] = useState('')
  const [busy, setBusy] = useState('')
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])

  const load = useCallback(async () => {
    if (mode === 'checking') return
    if (mode !== 'live') {
      setCatalogs((now) => now ?? DEMO)
      setDrafts((now) => (now.length ? now : DEMO_DRAFTS))
      return
    }
    try {
      const [packs, found] = await Promise.all([get<ApiPack[]>('/api/packs'), get<{ items: ApiDraft[] }>('/api/packs/drafts').catch(() => ({ items: [] }))])
      if (!alive.current) return
      setCatalogs(packs.map(tidy))
      setDrafts(found.items.map((row) => ({ slug: row.slug, name: row.name || row.slug, version: row.version ?? '', error: row.error ?? '', installed: row.installed_as ?? '' })))
    } catch (error) {
      if (alive.current) setProblem(error instanceof Error ? error.message : 'Could not read the catalogs.')
    }
  }, [mode])

  useEffect(() => {
    void load()
  }, [load])

  /** One change at a time. The key of the change is kept in `busy` so the row can say so. */
  const act = useCallback(
    async (key: string, live: () => Promise<unknown>, demo: () => void) => {
      setProblem('')
      setBusy(key)
      try {
        if (mode === 'live') {
          await live()
          await load()
        } else demo()
      } catch (error) {
        if (alive.current) setProblem(error instanceof Error ? error.message : 'It did not work.')
      } finally {
        if (alive.current) setBusy('')
      }
    },
    [mode, load],
  )

  const setEnabled = useCallback(
    (id: string, enabled: boolean) =>
      act(
        id,
        () => post(`/api/packs/${seg(id)}/enabled?enabled=${enabled}`),
        () => setCatalogs((now) => (now ?? []).map((row) => (row.id === id ? { ...row, enabled } : row))),
      ),
    [act],
  )

  const stepBack = useCallback(
    (id: string) =>
      act(
        id,
        () => post(`/api/packs/${seg(id)}/rollback`),
        () => setCatalogs((now) => (now ?? []).map((row) => (row.id === id && row.previous ? { ...row, version: row.previous, previous: '' } : row))),
      ),
    [act],
  )

  const install = useCallback(
    (slug: string) =>
      act(
        slug,
        () => post(`/api/packs/drafts/${seg(slug)}/install`),
        () => {
          const draft = DEMO_DRAFTS.find((row) => row.slug === slug)
          if (!draft) return
          setDrafts((now) => now.map((row) => (row.slug === slug ? { ...row, installed: slug } : row)))
          setCatalogs((now) => [...(now ?? []), { id: slug, name: draft.name, version: draft.version, previous: '', enabled: true, products: 5, risks: 14, sources: 20 }])
        },
      ),
    [act],
  )

  const discard = useCallback(
    (slug: string) =>
      act(
        slug,
        () => del(`/api/packs/drafts/${seg(slug)}`),
        () => setDrafts((now) => now.filter((row) => row.slug !== slug)),
      ),
    [act],
  )

  return { catalogs, drafts, problem, busy, setEnabled, stepBack, install, discard }
}
