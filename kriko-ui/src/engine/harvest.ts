/** The shareable half of a harvest job's result.
 *
 *  `pack_harvest` returns one row per catalog that gained a claim, and the row's
 *  `artifact` is a path the engine itself serves (`GET
 *  /api/packs/drafts/{slug}/artifact`) — a path, not an address, because the
 *  engine binds an OS-chosen port (`app/sidecar.py` prints it; the page is never
 *  told). The window therefore joins the path to the base every engine call
 *  already uses (`engineUrl`), never to a port of its own.
 *
 *  Nothing here invents a row: a result without `packs` — an author run, a job
 *  that failed before filing — shares nothing, and a row whose `artifact` is
 *  empty is not drawn as a link to nowhere. */

export interface SharedPack {
  slug: string
  pack_id: string
  name: string
  /** The engine's own path to the `.kpack`, exactly as it sent it. */
  artifact: string
}

const text = (value: unknown) => (typeof value === 'string' ? value : '')

export function sharedPacks(result: unknown): SharedPack[] {
  if (!result || typeof result !== 'object') return []
  const packs = (result as { packs?: unknown }).packs
  if (!Array.isArray(packs)) return []
  const out: SharedPack[] = []
  for (const row of packs) {
    if (!row || typeof row !== 'object') continue
    const one = row as Record<string, unknown>
    const artifact = text(one.artifact)
    // The result says what to share; a row without it is not a shareable pack.
    if (!artifact) continue
    out.push({
      slug: text(one.slug),
      pack_id: text(one.pack_id),
      name: text(one.name),
      artifact,
    })
  }
  return out
}
