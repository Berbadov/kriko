import { useEffect, useState } from 'react'
import { useAppUpdate } from '../../engine/appupdate'
import { useAbout, useKeys, usePrefsDoc, useSpent, type KeyRow } from '../../engine/settings'
import { usePrefs, type Profile, type ThemePref } from '../../prefs'
import { startTour } from '../../tour/Tour'
import { Chip, Segmented, Select, Switch } from '../controls'

const THEMES: { value: ThemePref; label: string }[] = [
  { value: 'system', label: 'System' },
  { value: 'dark', label: 'Dark' },
  { value: 'light', label: 'Light' },
]
const PROFILES: { value: Profile; label: string }[] = [
  { value: 'calm', label: 'Calm' },
  { value: 'standard', label: 'Standard' },
  { value: 'vivid', label: 'Vivid' },
]
const PARALLEL = [1, 2, 3, 4].map((n) => ({ value: String(n), label: String(n) }))
const SOURCE_COUNTS = [0, 5, 10, 20, 50]
/** The engine's labels are sentences. The choices need a word. */
const KIND_NAMES: Record<string, string> = {
  forums: 'Forums',
  reviews: 'Reviews',
  recalls: 'Recalls',
  manufacturer: 'Maker pages',
  video: 'Video',
  news: 'News',
}

/** Look, research, keys, spend, and what is installed. */
export function SettingsPanel(_: { onOpen?: (lookupId: string) => void }) {
  const { theme, setTheme, profile, setProfile, reduce, setReduce } = usePrefs()
  const { doc, problem, save } = usePrefsDoc()
  const spent = useSpent()
  const about = useAbout()
  const update = useAppUpdate()

  return (
    <div className="panel-body">
      <section className="panel-group">
        <h3>Look</h3>
        <div className="setting">
          <span>Theme</span>
          <Segmented label="Theme" value={theme} options={THEMES} onChange={setTheme} />
        </div>
        <div className="setting">
          <span>Motion</span>
          <Segmented label="Motion" value={profile} options={PROFILES} onChange={setProfile} />
        </div>
        <div className="setting">
          <span>Reduce motion</span>
          <Switch label="Reduce motion" on={reduce} onChange={setReduce} />
        </div>
        <div className="setting">
          <span>
            Tour
            <small>A short walk through the window.</small>
          </span>
          <button className="btn" onClick={startTour}>
            Take the tour
          </button>
        </div>
      </section>

      {problem && <p className="error-note">{problem}</p>}

      {doc && (
        <section className="panel-group">
          <h3>Research</h3>
          <div className="setting">
            <span>
              Products at once
              <small>Each one uses an agent.</small>
            </span>
            <Segmented
              label="Products at once"
              value={doc.chosen.run_concurrency || '4'}
              options={PARALLEL}
              onChange={(value) => void save({ run_concurrency: value })}
            />
          </div>
          <div className="setting">
            <span>
              Extra sources
              <small>Pages to read for each product. 0 is the default.</small>
            </span>
            <Select
              label="Extra sources"
              value={String(doc.research.sources)}
              options={(SOURCE_COUNTS.includes(doc.research.sources) ? SOURCE_COUNTS : [doc.research.sources, ...SOURCE_COUNTS]).map((n) => ({ value: String(n), label: String(n) }))}
              onChange={(value) => void save({ research_sources: value })}
            />
          </div>
          <div className="setting stack" data-tour="source-kinds">
            <span>Where to look</span>
            <div className="choices">
              {doc.source_kinds.map((kind) => {
                const on = doc.research.kinds.includes(kind.id)
                return (
                  <Chip
                    key={kind.id}
                    on={on}
                    onChange={(next) => {
                      const kinds = next ? [...doc.research.kinds, kind.id] : doc.research.kinds.filter((id) => id !== kind.id)
                      // One kind has to stay, or research has nowhere to look.
                      if (kinds.length) void save({ research_source_kinds: kinds.join(',') })
                    }}
                  >
                    {KIND_NAMES[kind.id] ?? kind.id}
                  </Chip>
                )
              })}
            </div>
          </div>
          <div className="setting">
            <span>
              Search service
              <small>{doc.search_providers.some((p) => p.ready) ? 'Used for the web search.' : 'Add a key below.'}</small>
            </span>
            <Select
              label="Search service"
              value={doc.chosen.search_provider || ''}
              options={[{ value: '', label: 'Automatic' }, ...doc.search_providers.map((p) => ({ value: p.id, label: p.ready ? p.label : `${p.label} (no key)` }))]}
              onChange={(value) => void save({ search_provider: value })}
            />
          </div>
          <div className="setting stack">
            <span>
              OpenAI-compatible endpoint
              <small>Optional API root for OpenAI-compatible services. Leave blank for OpenAI or the LLM_BASE_URL environment setting.</small>
            </span>
            <EndpointField value={doc.chosen.llm_base_url || ''} onSave={(value) => save({ llm_base_url: value })} />
          </div>
          <div className="setting stack">
            <span>
              Completion model
              <small>Model ID accepted by this endpoint for paid research. Leave blank to use its default.</small>
            </span>
            <ModelField value={doc.chosen.llm_model || ''} onSave={(value) => save({ llm_model: value })} />
          </div>
        </section>
      )}

      <KeysGroup />

      {spent && (
        <section className="panel-group">
          <h3>Spent in {spent.days} days</h3>
          <div className="tiles">
            <div>
              <strong>{spent.runs}</strong>
              <small>runs</small>
            </div>
            <div>
              <strong>{spent.tokens >= 1000 ? `${Math.round(spent.tokens / 1000)}k` : spent.tokens}</strong>
              <small>tokens</small>
            </div>
            <div>
              <strong>${spent.usd.toFixed(2)}</strong>
              <small>billed</small>
            </div>
          </div>
        </section>
      )}

      {about && (
        <section className="panel-group">
          <h3>About</h3>
          <div className="setting">
            <span>Engine</span>
            <span className="value">{about.version || '—'}</span>
          </div>
          <div className="setting">
            <span>
              Updates
              <small>
                {update.phase === 'downloading'
                  ? 'Downloading…'
                  : update.phase === 'installing'
                    ? 'Installing. Kriko opens again by itself.'
                    : update.problem ||
                      (update.release ? `Kriko ${update.release.version} is available.` : update.checked ? 'This is the newest version.' : 'Looked for on its own while Kriko is open.')}
              </small>
            </span>
            {update.release && update.canInstall ? (
              <button className="btn primary" onClick={() => void update.install()} disabled={update.phase !== 'idle'}>
                Update now
              </button>
            ) : (
              <button className="btn ghost" onClick={() => void update.check()} disabled={update.phase !== 'idle'}>
                {update.phase === 'checking' ? 'Checking…' : 'Check now'}
              </button>
            )}
          </div>
          <div className="setting stack">
            <span>Your data</span>
            <small className="panel-path">{about.folder || '—'}</small>
          </div>
        </section>
      )}
    </div>
  )
}

function EndpointField({ value, onSave }: { value: string; onSave: (value: string) => Promise<void> }) {
  const [draft, setDraft] = useState(value)
  useEffect(() => setDraft(value), [value])
  return (
    <input
      type="url"
      autoComplete="url"
      spellCheck={false}
      aria-label="OpenAI-compatible endpoint"
      placeholder="https://api.openai.com/v1"
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={() => {
        const next = draft.trim().replace(/\/$/, '')
        if (next !== value) void onSave(next)
      }}
      onKeyDown={(event) => {
        if (event.key === 'Enter') event.currentTarget.blur()
      }}
    />
  )
}

function ModelField({ value, onSave }: { value: string; onSave: (value: string) => Promise<void> }) {
  const [draft, setDraft] = useState(value)
  useEffect(() => setDraft(value), [value])
  return (
    <input
      type="text"
      autoComplete="off"
      spellCheck={false}
      aria-label="Completion model"
      placeholder="gpt-4o-mini"
      value={draft}
      onChange={(event) => setDraft(event.target.value)}
      onBlur={() => {
        const next = draft.trim()
        if (next !== value) void onSave(next)
      }}
      onKeyDown={(event) => {
        if (event.key === 'Enter') event.currentTarget.blur()
      }}
    />
  )
}

function KeysGroup() {
  const { doc, problem, tested, set, remove, test } = useKeys()
  if (!doc) return null
  return (
    <section className="panel-group">
      <h3>Keys</h3>
      <p className="panel-note">A key stays on this computer. The engine never sends it back.</p>
      {problem && <p className="error-note">{problem}</p>}
      <ul className="key-list">
        {doc.providers.map((row) => (
          <KeyItem key={row.id} row={row} result={tested[row.id] ?? ''} onSave={(value) => set(row.id, value)} onRemove={() => void remove(row.id)} onTest={() => void test(row.id)} />
        ))}
      </ul>
    </section>
  )
}

function KeyItem({
  row,
  result,
  onSave,
  onRemove,
  onTest,
}: {
  row: KeyRow
  result: string
  onSave: (value: string) => Promise<void>
  onRemove: () => void
  onTest: () => void
}) {
  const [value, setValue] = useState('')
  const [editing, setEditing] = useState(false)
  const label = row.label.replace(/ \(.*\)$/, '')

  const submit = async () => {
    if (!value.trim()) return
    await onSave(value)
    setValue('')
    setEditing(false)
  }

  return (
    <li className="key" data-present={row.present}>
      <div className="key-head">
        <span>
          <strong>{label}</strong>
          <small>{row.present ? `Set${row.hint ? ` · ends ${row.hint}` : ''}${row.source === 'env' ? ' · from the environment' : ''}` : 'Not set'}</small>
        </span>
        {!editing && (
          <span className="key-actions">
            {row.present && <button onClick={onTest}>Test</button>}
            <button onClick={() => setEditing(true)}>{row.present ? 'Change' : 'Add'}</button>
            {row.present && row.source !== 'env' && <button onClick={onRemove}>Remove</button>}
          </span>
        )}
      </div>
      {editing && (
        <form
          className="key-form"
          onSubmit={(event) => {
            event.preventDefault()
            void submit()
          }}
        >
          <input
            type="password"
            autoComplete="off"
            spellCheck={false}
            autoFocus
            placeholder={`${label} key`}
            aria-label={`${label} key`}
            value={value}
            onChange={(event) => setValue(event.target.value)}
          />
          <button type="submit" className="btn" disabled={!value.trim()}>
            Save
          </button>
          <button
            type="button"
            onClick={() => {
              setValue('')
              setEditing(false)
            }}
          >
            Cancel
          </button>
        </form>
      )}
      {result && <small className="key-result">{result}</small>}
    </li>
  )
}
