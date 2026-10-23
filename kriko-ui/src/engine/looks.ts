/** The saved quick looks a catalog has not claimed, as `/api/history/records`
 *  describes them.
 *
 *  The records route is the one surface that carries both a saved look's job id
 *  (`lookup_id` is `job:<id>`) and the categorization the engine kept beside it,
 *  plus `categorization_catalogs` — the installed catalogs a choice may name.
 *  `POST /api/quick-looks/{id}/category` validates against exactly that list, so
 *  the screen offers the engine's list rather than a second one of its own.
 *
 *  An abstention is a status other than `assigned`, and it is kept as an open
 *  question (`openQuestion`, the engine's own sentence), never as a catalog.
 *  `docs/USAGE.md` is explicit that filing is not permission to invent an
 *  assignment; this module therefore has no default and no fallback catalog. */

export interface SavedCatalog {
  pack_id: string
  name: string
  enabled: boolean
  editable: boolean
}

export interface SavedLook {
  /** The record's own id, `job:<job_id>`. */
  id: string
  /** The quick look job the two category routes name. Empty when the record
   *  was not a job, which the screen reads as "nothing to file". */
  jobId: string
  name: string
  createdAt: string
  status: string
  problems: number
  /** The catalog the engine filed it under. Empty while it has abstained. */
  assignedTo: string
  /** The engine's word for how it was decided: `reader`, `agent`, `deterministic`. */
  decidedBy: string
  /** Why the engine abstained, in its own words. Empty when it assigned one. */
  openQuestion: string
}

interface ApiCategorization {
  status?: unknown
  pack_id?: unknown
  pack_name?: unknown
  method?: unknown
  message?: unknown
}

interface ApiRecord {
  lookup_id?: unknown
  created_at?: unknown
  label?: unknown
  source?: unknown
  status?: unknown
  claim_count?: unknown
  categorization?: unknown
}

const text = (value: unknown) => (typeof value === 'string' ? value : '')

const object = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' ? (value as Record<string, unknown>) : {}

export function savedLooks(reply: unknown): { looks: SavedLook[]; catalogs: SavedCatalog[] } {
  const body = object(reply)
  const catalogs: SavedCatalog[] = []
  for (const row of Array.isArray(body.categorization_catalogs) ? body.categorization_catalogs : []) {
    const one = object(row)
    const packId = text(one.pack_id)
    if (!packId) continue
    catalogs.push({
      pack_id: packId,
      name: text(one.name) || packId,
      enabled: Boolean(one.enabled),
      editable: Boolean(one.editable),
    })
  }

  const looks: SavedLook[] = []
  for (const row of Array.isArray(body.items) ? body.items : []) {
    const one = row as ApiRecord
    // A quick look record, not a saved check, a pack build or a queue row: only
    // a quick look has a job either category route names. Its `status` is
    // carried along, because both routes refuse one that has not finished.
    if (text(one.source) !== 'quick_look') continue
    const assignment = object(one.categorization) as ApiCategorization
    const assigned = text(assignment.status) === 'assigned'
    const id = text(one.lookup_id)
    looks.push({
      id,
      jobId: id.startsWith('job:') ? id.slice(4) : '',
      name: text(one.label),
      createdAt: text(one.created_at),
      status: text(one.status),
      problems: typeof one.claim_count === 'number' ? one.claim_count : 0,
      assignedTo: assigned ? text(assignment.pack_name) || text(assignment.pack_id) : '',
      decidedBy: assigned ? text(assignment.method) : '',
      openQuestion: assigned ? '' : text(assignment.message),
    })
  }
  return { looks, catalogs }
}
