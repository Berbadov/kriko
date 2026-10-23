import { useRef, useState } from 'react'
import { engineUrl, get, inShell, post, uploadArtifact, seg } from '../../engine/api'
import { followJob } from '../../engine/jobs'
import { useEngine } from '../../engine/Engine'
import { useCatalogs, type Catalog, type Draft } from '../../engine/catalogs'
import { sharedPacks, type SharedPack } from '../../engine/harvest'
import { useMarks, type Mark } from '../../engine/marks'
import { ago, askAgentToCategorizeLook, assignSavedLook, useSavedLooks } from '../../engine/history'
import type { SavedCatalog, SavedLook } from '../../engine/looks'
import { Select, Switch } from '../controls'

const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

/** The engine's closed verdict vocabulary, written as words. `wrong` and
 *  `useful` are already words; the third is the only one with an underscore,
 *  and the engine's `verdicts` list is the only place the set comes from. */
const verdictWord = (verdict: string) => verdict.replaceAll('_', ' ')

const reason = (error: unknown, fallback: string) => (error instanceof Error ? error.message : fallback)

/** What Kriko knows. A catalog is on or off, and a draft from an agent waits for the reader to install it. */
export function CatalogsPanel() {
  const { catalogs, drafts, problem, busy, setEnabled, stepBack, install, discard, reload } = useCatalogs()
  const [asking, setAsking] = useState<string | null>(null)
  const { mode, preferred } = useEngine()
  const [status, setStatus] = useState('')
  const [working, setWorking] = useState(false)
  const [category, setCategory] = useState('')
  const [available, setAvailable] = useState<{pack_id: string; name: string; state: string; offered_version: string}[]>([])
  /** The catalogs the last harvest said gained a claim, with the `.kpack` path
   *  the job itself sent (`tasks.pack_harvest`). Cleared when another job starts
   *  so an old link is never shown as this run's. */
  const [shared, setShared] = useState<SharedPack[]>([])
  const input = useRef<HTMLInputElement>(null)
  // The reader's own marks, read from the engine. `null` means "not this
  // window's to draw" (demo has no engine), which is not an empty list.
  const marks = useMarks()
  const saved = useSavedLooks()

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
    } catch (error) { setStatus(error instanceof Error ? error.message : 'The operation failed. Try again.') }
    finally { setWorking(false) }
  }

  const discover = async () => {
    setWorking(true)
    try {
      const found = await get<{packs: typeof available; error?: string}>('/api/packs/updates?fresh=true', 30000)
      if (found.error) throw new Error(found.error)
      setAvailable(found.packs)
      setStatus(found.packs.length ? 'Release catalogs loaded.' : 'No release catalogs are available.')
    } catch (error) { setStatus(error instanceof Error ? error.message : 'Could not load catalogs.') }
    finally { setWorking(false) }
  }

  const importFile = async (file?: File) => {
    if (!file) return
    setWorking(true)
    try { await uploadArtifact('/api/packs/import', file); await reload(); setStatus('Catalog installed.') }
    catch (error) { setStatus(error instanceof Error ? error.message : 'The catalog could not be installed.') }
    finally { setWorking(false); if (input.current) input.current.value = '' }
  }

  // A failed read is not a wait. `{problem || 'Reading the catalogs…'}` rendered
  // both in the muted note style, so a refusal looked like a slow screen.
  if (!catalogs && problem) {
    return (
      <p className="error-note" role="alert">
        Your catalogs could not be read. {problem}
      </p>
    )
  }
  if (!catalogs) return <p className="panel-note">Reading the catalogs…</p>

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

  return (
    <div className="panel-body">
      {problem && <p className="error-note">{problem}</p>}
      <section className="panel-group">
        <h3>Get product knowledge</h3>
        <input ref={input} hidden type="file" accept=".kpack" onChange={(event) => void importFile(event.target.files?.[0])} />
        <div className="card-actions">
          <button className="btn" disabled={working || mode !== 'live'} onClick={() => void discover()}>Find release catalogs</button>
          <button className="btn" disabled={working || mode !== 'live'} onClick={() => input.current?.click()}>Import .kpack</button>
          <button className="btn" disabled={working || mode !== 'live'} onClick={() => void job('/api/packs/update', {})}>Update catalogs</button>
          <button className="btn" disabled={working || mode !== 'live'} onClick={() => void job('/api/packs/harvest', {})}>File saved Quick Looks</button>
        </div>
        {status && <p role="status">{status}</p>}
        {/* What a harvest produced is shareable: the job's own result names each
            catalog that gained a claim and the engine path to its `.kpack`. The
            path is joined to the base every call uses, never to a port — the
            engine binds an OS-chosen one. The packaged window is not served by
            the engine, so following the same path there would replace Kriko
            with the shell's 404; the shell would have to hand the bytes over,
            which `engine_request` cannot do (it reads a reply as text). */}
        {shared.length > 0 && (
          <ul className="plain-list share-list">
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
        {available.map((row) => <div className="setting" key={row.pack_id}><span>{row.name} · {row.offered_version}<small>{row.state.replaceAll('_', ' ')}</small></span><button className="btn" disabled={working || !['not_installed', 'available'].includes(row.state)} onClick={() => void job('/api/packs/update', {pack_id: row.pack_id})}>Install or update</button></div>)}
      </section>
      <section className="panel-group">
        <h3>Create a catalog draft</h3>
        <p>Describe the category and research you need. The selected agent researches a draft; you review it before installing.</p>
        <textarea aria-label="Catalog to research" value={category} onChange={(event) => setCategory(event.target.value)} maxLength={500} placeholder="For example: cordless drills sold in my market" />
        <button className="btn" disabled={working || mode !== 'live' || !category.trim()} onClick={() => void job('/api/packs/author', {category, harness: preferred})}>Research draft</button>
      </section>

      {/* Filing is not permission to invent an assignment: a saved look the
          engine could not classify keeps its open question and takes a catalog
          only from the reader's press. The candidates are the engine's own
          `categorization_catalogs`, the same list the route validates against. */}
      {saved.problem && (
        <p className="error-note" role="alert">
          Your saved Quick Looks could not be read. {saved.problem}{' '}
          <button className="btn" onClick={() => void saved.reload()}>Try again</button>
        </p>
      )}
      {unfiled.length > 0 && (
        <section className="panel-group">
          <h3>Quick looks with no catalog yet</h3>
          <ul className="past-list">
            {unfiled.map((look) => (
              <SavedLookRow key={look.id} look={look} catalogs={saved.catalogs} onSaved={() => void saved.reload()} />
            ))}
          </ul>
        </section>
      )}

      <section className="panel-group">
        <h3>Installed</h3>
        {marks.problem && (
          <p className="error-note" role="alert">
            Your marks could not be read. {marks.problem}{' '}
            <button className="btn" onClick={() => void marks.reload()}>Try again</button>
          </p>
        )}
        {marks.marks && (
          <p className="panel-note mark-summary">
            {marked > 0
              ? `You marked ${count(marked, 'claim', 'claims')}${breakdown ? `: ${breakdown}` : ''}.`
              : 'No claim is marked yet. A mark you add from a result page is kept here.'}
          </p>
        )}
        {catalogs.length === 0 && <p className="panel-note">No catalogs yet. Kriko still checks a product from what it finds on the page.</p>}
        <ul className="past-list">
          {catalogs.map((row) => (
            <CatalogRow
              key={row.id}
              row={row}
              working={busy === row.id}
              asking={asking === `back:${row.id}`}
              marks={(marks.marks ?? []).filter((mark) => mark.pack_id === row.id)}
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
      </section>

      {/* A mark snapshots its pack id and claim title, so a mark outlives the
          catalog it was made in. Dropping these would lose the reader's own
          notes the day they remove a catalog, which is the opposite of what
          `claim_marks` is for. */}
      {orphans.length > 0 && (
        <section className="panel-group">
          <h3>Marks from catalogs you no longer have</h3>
          <ul className="past-list">
            {orphans.map((mark) => (
              <li className="past" key={`${mark.pack_id}/${mark.claim_id}`}>
                <span className="past-main">
                  <strong>{mark.title || mark.claim_id}</strong>
                  <small>{verdictWord(mark.verdict)} · catalog {mark.pack_id} · {ago(mark.updated_at)}</small>
                  {mark.note && <small className="mark-note">{mark.note}</small>}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {waiting.length > 0 && (
        <section className="panel-group">
          <h3>Drafted for you</h3>
          <ul className="past-list">
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
    </div>
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
    <li className="past look" aria-busy={working}>
      <span className="past-main">
        <strong>{look.name || 'Quick look'}</strong>
        <small>{meta}</small>
        {look.openQuestion && <small className="look-question">{look.openQuestion}</small>}
        <span className="look-choose">
          <Select
            label={`Catalog for ${look.name || 'this quick look'}`}
            value={pick}
            onChange={setPick}
            options={[{ value: '', label: 'Choose a catalog' }, ...catalogs.map((row) => ({ value: row.pack_id, label: row.name }))]}
          />
          <button className="btn" disabled={working || !pick} onClick={() => void file()}>Use this catalog</button>
          <button className="btn ghost" disabled={working} onClick={() => void ask()}>Ask the agent to name it</button>
        </span>
        {note && <small className="look-note" role="status">{note}</small>}
      </span>
    </li>
  )
}

function CatalogRow({
  row,
  working,
  asking,
  marks,
  onToggle,
  onAsk,
  onKeep,
  onBack,
}: {
  row: Catalog
  working: boolean
  asking: boolean
  marks: Mark[]
  onToggle: (on: boolean) => void
  onAsk: () => void
  onKeep: () => void
  onBack: () => void
}) {
  const meta = [`v${row.version}`, count(row.products, 'product', 'products'), count(row.risks, 'risk', 'risks')].join(' · ')
  return (
    <li className="past catalog" data-asking={asking} data-off={!row.enabled} aria-busy={working}>
      <span className="past-main">
        <strong>{row.name}</strong>
        <small>{meta}</small>
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
          <button className="step-back" onClick={onAsk} disabled={working}>
            Go back to v{row.previous}
          </button>
        )}
      </span>
      {asking ? (
        <span className="past-ask calm">
          <span>Go back?</span>
          <button className="install" onClick={onBack}>Go back</button>
          <button onClick={onKeep}>Keep</button>
        </span>
      ) : (
        <Switch on={row.enabled} onChange={onToggle} label={`Use ${row.name}`} />
      )}
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
    <li className="past" data-asking={asking} aria-busy={working}>
      <span className="past-main">
        <strong>{row.name}</strong>
        <small>{row.error || (row.version ? `v${row.version}` : 'Draft')}</small>
        <button className="btn ghost" onClick={() => void inspect()}>Review draft</button>
        {previewProblem && <span className="error-note" role="alert">{previewProblem}</span>}
        {preview && <details open><summary>{preview.subjects.length} products · {preview.claims} sourced problems</summary><p>{preview.principle}</p><ul>{preview.subjects.map((name) => <li key={name}>{name}</li>)}</ul>{preview.uncovered.length > 0 && <p>{preview.uncovered.length} coverage gaps remain.</p>}</details>}
      </span>
      {asking ? (
        <span className="past-ask">
          <span>Discard?</span>
          <button onClick={onDiscard}>Discard</button>
          <button onClick={onKeep}>Keep</button>
        </span>
      ) : (
        <span className="past-ask calm">
          {!row.error && (
            <button className="install" onClick={onInstall} disabled={working}>
              {working ? 'Installing…' : 'Install'}
            </button>
          )}
          <button onClick={onAsk} disabled={working}>
            Discard
          </button>
        </span>
      )}
    </li>
  )
}
