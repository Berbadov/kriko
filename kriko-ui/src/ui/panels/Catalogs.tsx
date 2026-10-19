import { useRef, useState } from 'react'
import { get, post, uploadArtifact, seg } from '../../engine/api'
import { followJob } from '../../engine/jobs'
import { useEngine } from '../../engine/Engine'
import { useCatalogs, type Catalog, type Draft } from '../../engine/catalogs'
import { Switch } from '../controls'

const count = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

/** What Kriko knows. A catalog is on or off, and a draft from an agent waits for the reader to install it. */
export function CatalogsPanel() {
  const { catalogs, drafts, problem, busy, setEnabled, stepBack, install, discard, reload } = useCatalogs()
  const [asking, setAsking] = useState<string | null>(null)
  const { mode, preferred } = useEngine()
  const [status, setStatus] = useState('')
  const [working, setWorking] = useState(false)
  const [category, setCategory] = useState('')
  const [available, setAvailable] = useState<{pack_id: string; name: string; state: string; offered_version: string}[]>([])
  const input = useRef<HTMLInputElement>(null)

  const job = async (path: string, body: object) => {
    setWorking(true)
    setStatus('Starting…')
    try {
      const sent = await post<{job_id: string}>(path, body)
      const ended = await followJob(sent.job_id, (reading) => setStatus(reading.message || 'Working…'))
      if (ended?.state !== 'succeeded') throw new Error(ended?.message || 'The operation did not finish.')
      setStatus(ended.message || 'Finished')
      await reload()
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

  if (!catalogs) return <p className="panel-note">{problem || 'Reading the catalogs…'}</p>

  const waiting = drafts.filter((row) => !row.installed)

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
        {available.map((row) => <div className="setting" key={row.pack_id}><span>{row.name} · {row.offered_version}<small>{row.state.replaceAll('_', ' ')}</small></span><button className="btn" disabled={working || !['not_installed', 'available'].includes(row.state)} onClick={() => void job('/api/packs/update', {pack_id: row.pack_id})}>Install or update</button></div>)}
      </section>
      <section className="panel-group">
        <h3>Create a catalog draft</h3>
        <p>Describe the category and research you need. The selected agent researches a draft; you review it before installing.</p>
        <textarea aria-label="Catalog to research" value={category} onChange={(event) => setCategory(event.target.value)} maxLength={500} placeholder="For example: cordless drills sold in my market" />
        <button className="btn" disabled={working || mode !== 'live' || !category.trim()} onClick={() => void job('/api/packs/author', {category, harness: preferred})}>Research draft</button>
      </section>

      <section className="panel-group">
        <h3>Installed</h3>
        {catalogs.length === 0 && <p className="panel-note">No catalogs yet. Kriko still checks a product from what it finds on the page.</p>}
        <ul className="past-list">
          {catalogs.map((row) => (
            <CatalogRow
              key={row.id}
              row={row}
              working={busy === row.id}
              asking={asking === `back:${row.id}`}
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

function CatalogRow({
  row,
  working,
  asking,
  onToggle,
  onAsk,
  onKeep,
  onBack,
}: {
  row: Catalog
  working: boolean
  asking: boolean
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
