import { useEffect, useState, type CSSProperties } from 'react'
import { CAP_ORDER, CAP_WORDS, usedToday, useCaps, type CapResource } from '../../engine/caps'
import { useAppUpdate } from '../../engine/appupdate'
import { useSensitivity } from '../../engine/sensitivity'
import { useAbout, useKeys, usePrefsDoc, usePresence, useSharedAccess, useSpent, type KeyRow } from '../../engine/settings'
import type { Sensitivity } from '../../engine/thinness'
import { useUsage } from '../../engine/usage'
import { usePrefs, type Profile, type ThemePref } from '../../prefs'
import { startTour } from '../../tour/Tour'
import { Chip, Segmented, Select, Switch } from '../controls'
import { showDrawer } from '../drawerEvents'
import { McpClientsGroup } from './McpClients'
import { ProxiesGroup } from './Proxies'
import { SearchProvidersGroup } from './SearchProviders'
import { SETTINGS_PAGES, onSettingsPage, takeRequestedSettingsPage, type SettingsPage } from './settingsPages'

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
/** What each choice does is the hover hint, so the row stays a label and a control. */
const SENSITIVITY: { value: Sensitivity; label: string; hint: string }[] = [
  { value: 'all', label: 'Show everything', hint: 'Every finding is drawn, with its indicator.' },
  { value: 'hide_thin', label: 'Hide thin', hint: 'Findings with two or more reasons for doubt are hidden, and counted so you can show them.' },
  { value: 'strict', label: 'Strict', hint: 'Only findings with no reason for doubt are drawn. The rest are counted.' },
]
const PARALLEL = [1, 2, 3, 4].map((n) => ({ value: String(n), label: String(n) }))
const SOURCE_COUNTS = [0, 5, 10, 20, 50]
const LANGUAGES = [
  ['en', 'English'], ['es', 'Spanish'], ['fr', 'French'], ['de', 'German'],
  ['it', 'Italian'], ['pt', 'Portuguese'], ['nl', 'Dutch'], ['pl', 'Polish'],
  ['tr', 'Turkish'], ['ru', 'Russian'], ['ja', 'Japanese'], ['ko', 'Korean'],
  ['zh', 'Chinese'], ['ar', 'Arabic'],
].map(([value, label]) => ({ value, label }))
/** The engine's labels are sentences. The choices need a word. */
const KIND_NAMES: Record<string, string> = {
  forums: 'Forums',
  reviews: 'Reviews',
  recalls: 'Recalls',
  manufacturer: 'Maker pages',
  video: 'Video',
  news: 'News',
}

/** Look, research, keys, connections, and usage. One page is drawn at a time, so
 *  the drawer is a short list of choices instead of one long scroll. */
export function SettingsPanel(_: { onOpen?: (lookupId: string) => void }) {
  const { theme, setTheme, profile, setProfile, reduce, setReduce } = usePrefs()
  const { doc, problem, save } = usePrefsDoc()
  const spent = useSpent()
  const about = useAbout()
  const { presence, reload: reloadPresence } = usePresence()
  const update = useAppUpdate()
  const { sensitivity, choose } = useSensitivity()
  const { caps, setCap } = useCaps()
  const { meters, demo: demoMeters } = useUsage()
  const [sensitivityProblem, setSensitivityProblem] = useState('')
  const [page, setPage] = useState<SettingsPage>(() => takeRequestedSettingsPage() ?? 'look')
  useEffect(() => onSettingsPage(setPage), [])

  return (
    <div className="panel-body settings">
      <div className="settings-nav">
        <Segmented label="Settings page" value={page} options={SETTINGS_PAGES} onChange={setPage} />
      </div>
      {problem && <p className="error-note">{problem}</p>}

      <div className="settings-page" key={page}>
      {page === 'look' && (
        <>
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
              <span>Tour</span>
              <button className="btn" onClick={startTour}>
                Take the tour
              </button>
            </div>
          </section>

          <section className="panel-group">
            <h3>Information sensitivity</h3>
            <div className="setting stack">
              <span>How much doubt to show</span>
              <Segmented
                label="Information sensitivity"
                value={sensitivity}
                options={SENSITIVITY}
                onChange={(value) => void choose(value).then(setSensitivityProblem)}
              />
            </div>
            {sensitivityProblem && <p className="error-note">{sensitivityProblem}</p>}
          </section>

          <section className="panel-group">
            <h3>Chat</h3>
            <div className="setting">
              <span>Chat settings</span>
              <button className="btn" onClick={() => showDrawer('chat')}>
                Open
              </button>
            </div>
          </section>
        </>
      )}

      {page === 'research' && doc && (
        <>
          <section className="panel-group">
            <h3>How hard to look</h3>
            <div className="setting">
              <span>Products at once</span>
              <Segmented
                label="Products at once"
                value={doc.chosen.run_concurrency || '4'}
                options={PARALLEL}
                onChange={(value) => void save({ run_concurrency: value })}
              />
            </div>
            <RangeSetting
              label="Thoroughness"
              value={doc.research.thoroughness}
              note="Higher means more search calls."
              onSave={(value) => void save({ kriko_agent_thoroughness: String(value) })}
            />
            <RangeSetting
              label="Validation sensitivity"
              value={doc.research.validation_sensitivity}
              onSave={(value) => void save({ kriko_agent_validation_sensitivity: String(value) })}
            />
            <div className="setting">
              <span>Extra sources</span>
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
          </section>

          <section className="panel-group">
            <h3>Language and market</h3>
            <div className="setting">
              <span>Response language</span>
              <Select
                label="Response language"
                value={doc.chosen.local_output_language || 'auto'}
                options={[
                  { value: 'auto', label: 'Automatic' },
                  ...(doc.chosen.local_output_language && !LANGUAGES.some((one) => one.value === doc.chosen.local_output_language)
                    ? [{ value: doc.chosen.local_output_language, label: doc.chosen.local_output_language }]
                    : []),
                  ...LANGUAGES,
                ]}
                onChange={(value) => void save({ local_output_language: value })}
              />
            </div>
            <div className="setting">
              <span>Research language</span>
              <Select
                label="Research language"
                value={doc.chosen.local_search_language || 'en'}
                options={[
                  ...(doc.chosen.local_search_language && !LANGUAGES.some((one) => one.value === doc.chosen.local_search_language)
                    ? [{ value: doc.chosen.local_search_language, label: doc.chosen.local_search_language }]
                    : []),
                  ...LANGUAGES,
                ]}
                onChange={(value) => void save({ local_search_language: value })}
              />
            </div>
            <div className="setting">
              <span>Market region</span>
              <Select
                label="Market region"
                value={doc.chosen.market_region || 'auto'}
                options={doc.market_regions.map((region) => ({ value: region.id, label: region.label }))}
                onChange={(value) => void save({ market_region: value })}
              />
            </div>
          </section>

          <section className="panel-group">
            <h3>Model</h3>
            <div className="setting">
              <span>Product classification</span>
              <Select
                label="Product classification"
                value={doc.chosen.classification_provider || 'agent'}
                options={doc.classification_providers.map((provider) => ({
                  value: provider.id,
                  label: provider.ready ? provider.label : `${provider.label} (no key)`,
                }))}
                onChange={(value) => void save({ classification_provider: value })}
              />
            </div>
            <div className="setting stack">
              <span>OpenAI-compatible endpoint</span>
              <EndpointField value={doc.chosen.llm_base_url || ''} onSave={(value) => save({ llm_base_url: value })} />
            </div>
            <div className="setting stack">
              <span>Completion model</span>
              <ModelField value={doc.chosen.llm_model || ''} onSave={(value) => save({ llm_model: value })} />
            </div>
          </section>
        </>
      )}

      {page === 'keys' && (
        <>
          <KeysGroup />
          <SharedAccessGroup />
        </>
      )}

      {page === 'connections' && (
        <>
          <section className="panel-group">
            <h3>Setup</h3>
            <div className="setting">
              <span>Set up Kriko</span>
              <button className="btn" onClick={() => showDrawer('setup')}>
                Open
              </button>
            </div>
          </section>

          <SearchProvidersGroup />

          <ProxiesGroup />

          <McpClientsGroup />
        </>
      )}

      {page === 'usage' && (
        <>
          <section className="panel-group">
            <h3>Usage caps</h3>
            <p className="panel-note">A cap only warns. Nothing is blocked.</p>
            {CAP_ORDER.map((id) => (
              <CapField
                key={id}
                id={id}
                cap={caps[id]}
                today={usedToday(meters, id)}
                onChange={(value) => setCap(id, value)}
              />
            ))}
            {demoMeters && <p className="panel-note" data-kind="warn">Example numbers, because no engine answers.</p>}
          </section>

          {presence && (
            <section className="panel-group">
              <h3>Count me as using Kriko</h3>
              <div className="setting">
                <span>Anonymous daily ping</span>
                <Switch
                  label="Anonymous daily ping"
                  on={doc?.chosen.presence_enabled === '1' || presence.enabled}
                  onChange={(on) => void save({ presence_enabled: on ? '1' : '0' }).then(() => void reloadPresence())}
                />
              </div>
              <p className="panel-note" data-kind="data">
                Once a day: a random install id and the app version, nothing else. Read the <a href="https://kriko.cc/privacy/">privacy policy</a>.
              </p>
              {(doc?.chosen.presence_enabled === '1' || presence.enabled) && (
                <>
                  <div className="setting">
                    <span>Last sent</span>
                    <span className="value">{presence.last_day || 'On the next start'}</span>
                  </div>
                  {!presence.endpoint && <p className="panel-note" data-kind="data">No endpoint is set, so nothing leaves this computer.</p>}
                </>
              )}
            </section>
          )}

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
                  <small>measured spend</small>
                </div>
              </div>
              {!!spent.unpriced_runs && <p className="panel-note" data-kind="data">{spent.unpriced_runs} runs have no price, so the amount is partial.</p>}
            </section>
          )}

          {about && (
            <section className="panel-group">
              <h3>About</h3>
              <div className="setting">
                <span>Engine</span>
                <span className="value">{about.version || 'Not known'}</span>
              </div>
              <div className="setting">
                <span>Updates</span>
                <span className="setting-end">
                  {updateState(update) && <span className="state" data-tone={update.release ? 'ok' : 'none'}>{updateState(update)}</span>}
                  {update.release && (update.canInstall || update.release.engine) ? (
                    <button className="btn primary" onClick={() => void update.install()} disabled={update.phase !== 'idle'}>
                      Update now
                    </button>
                  ) : (
                    <button className="btn" onClick={() => void update.check()} disabled={update.phase !== 'idle'}>
                      {update.phase === 'checking' ? 'Checking…' : 'Check now'}
                    </button>
                  )}
                </span>
              </div>
              {update.problem && update.phase === 'idle' && <p className="error-note">{update.problem}</p>}
              <div className="setting">
                <span>Your data</span>
                <span className="value path">{about.folder || 'Not known'}</span>
              </div>
            </section>
          )}
        </>
      )}
      </div>
    </div>
  )
}

/** The one short state an update row shows beside its button. A problem is its own line. */
function updateState(update: ReturnType<typeof useAppUpdate>): string {
  if (update.phase === 'downloading') return 'Downloading…'
  if (update.phase === 'restarting') return 'Starting the new engine…'
  if (update.phase === 'installing') return 'Installing. Kriko opens again by itself.'
  if (update.problem) return ''
  if (update.release) return `Kriko ${update.release.version} is available`
  return update.checked ? 'Up to date' : ''
}

function CapField({ id, cap, today, onChange }: { id: CapResource; cap: number | null; today: number | null; onChange: (value: number | null) => void }) {
  const word = CAP_WORDS[id]
  const [draft, setDraft] = useState(cap === null ? '' : String(cap))
  useEffect(() => setDraft(cap === null ? '' : String(cap)), [cap])
  const commit = () => {
    const text = draft.trim()
    if (!text) { if (cap !== null) onChange(null); return }
    const value = Number(text.replace(',', '.'))
    if (!Number.isFinite(value) || value < 0) { setDraft(cap === null ? '' : String(cap)); return }
    if (value === 0) { if (cap !== null) onChange(null); setDraft(''); return }
    if (value !== cap) onChange(value)
  }
  const used = today === null ? '' : `${word.money ? `$${today.toFixed(today < 0.01 ? 4 : 2)}` : today.toLocaleString('en-GB')} today`
  return (
    <div className="setting">
      <span>
        {word.title} a day
        {used && <span className="state" data-tone="none">{used}</span>}
      </span>
      <label className="cap-field">
        <input type="number" min="0" step={word.money ? '0.01' : '1'} inputMode={word.money ? 'decimal' : 'numeric'} placeholder="No cap" aria-label={`${word.title} a day`} value={draft} onChange={(event) => setDraft(event.target.value)} onBlur={commit} onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur() }} />
        <span className="cap-unit">{word.money ? '$' : word.unit}</span>
      </label>
    </div>
  )
}

/** A dial from 0 to 100: its name and value on one line, the slider under them.
 *  `note` is for a dial that costs money, and is one short line. */
function RangeSetting({
  label,
  value,
  note,
  onSave,
}: {
  label: string
  value: number
  note?: string
  onSave: (value: number) => void
}) {
  const [draft, setDraft] = useState(value)
  useEffect(() => setDraft(value), [value])
  const commit = () => {
    if (draft !== value) onSave(draft)
  }

  return (
    <div className="setting stack tuning-setting">
      <span className="tuning-head">
        <span>{label}</span>
        <b className="mono">{draft}%</b>
      </span>
      <input
        className="tuning-range"
        style={{ '--fill': `${draft}%` } as CSSProperties}
        type="range"
        min={0}
        max={100}
        step={5}
        value={draft}
        aria-label={label}
        aria-valuetext={`${draft}%`}
        onChange={(event) => setDraft(event.currentTarget.valueAsNumber)}
        onPointerUp={commit}
        onKeyUp={commit}
        onBlur={commit}
      />
      {note && <small className="cost-note">{note}</small>}
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
      <p className="panel-note" data-kind="data">Keys stay on this computer. The engine never sends one back.</p>
      {problem && <p className="error-note">{problem}</p>}
      <ul className="key-list">
        {doc.providers.map((row) => (
          <KeyItem key={row.id} row={row} result={tested[row.id] ?? ''} onSave={(value) => set(row.id, value)} onRemove={() => void remove(row.id)} onTest={() => void test(row.id)} />
        ))}
      </ul>
    </section>
  )
}

/** Use someone else's keys for Kriko Agent, or hand a friend a password for yours. */
export function SharedAccessGroup() {
  const { doc, problem, code, unlock, forget, make } = useSharedAccess()
  const [pasted, setPasted] = useState('')
  const [password, setPassword] = useState('')
  const [label, setLabel] = useState('')
  const [madeWith, setMadeWith] = useState('')
  const [saving, setSaving] = useState(false)
  const unlockCode = async () => {
    setSaving(true)
    try {
      if (await unlock(pasted, password, label)) {
        setPassword(''); setPasted('')
      }
    } finally { setSaving(false) }
  }
  if (!doc) return null
  const trial = doc.trial
  const granted = doc.grant.present
  // Whether Kriko Agent is answering on somebody else's keys here. Every number
  // below is the engine's own (`/api/keys/shared/status`); the grant and the
  // trial are the only two states, so one short word says which one is in use.
  const fromWhom = doc.grant.label ? `${doc.grant.label}'s keys` : 'shared keys'
  const sharing = granted ? `On, ${fromWhom}` : trial.available ? 'On, free trial' : 'Off, your own keys'
  const trialState = trial.available
    ? `${trial.left} of ${trial.limit} questions left`
    : trial.used
      ? `Used up, ${trial.used} of ${trial.limit}`
      : 'Not in this build'

  return (
    <section className="panel-group" data-tour="shared-access">
      <h3>Shared access</h3>
      {problem && <p className="error-note">{problem}</p>}
      {!doc.bound && (
        <p className="panel-note" data-kind="warn">
          This build has no share pepper, so a code made elsewhere will not open here. Build one with{' '}
          <code>python tools/make_share_pepper.py</code>.
        </p>
      )}

      <div className="setting">
        <span>Sharing</span>
        <span className="setting-end">
          <span className="state" data-tone={granted || trial.available ? 'ok' : 'none'}>{sharing}</span>
          {granted && doc.device === 'dpapi' && <span className="state" data-tone="none">Bound to this Windows account</span>}
        </span>
      </div>
      {!granted && (
        <div className="setting">
          <span>Free trial</span>
          <span className="value">{trialState}</span>
        </div>
      )}
      {!granted && !trial.available && trial.used > 0 && (
        <p className="panel-note" data-kind="warn">Paste an access code or add your own keys on this page.</p>
      )}

      <div className="setting stack">
        <span>Access code</span>
        <textarea aria-label="Access code" className="key-field" rows={3} value={pasted} spellCheck={false} placeholder="Paste the code" onChange={(event) => setPasted(event.target.value)} />
      </div>
      <div className="setting stack">
        <span>Password</span>
        <input aria-label="Shared access password" className="key-field" type="password" autoComplete="off" placeholder="Sent apart from the code" value={password} onChange={(event) => setPassword(event.target.value)} />
      </div>
      <div className="setting stack">
        <span>Whose keys (optional)</span>
        <input aria-label="Whose keys" className="key-field" type="text" value={label} onChange={(event) => setLabel(event.target.value)} />
      </div>
      <p className="panel-note" data-kind="data">The password works in this app only. Keys are sealed on this computer.</p>
      <div className="setting actions">
        <button className="btn primary" disabled={saving || !pasted.trim() || !password} onClick={() => void unlockCode()}>
          {saving ? 'Opening code…' : 'Use these keys'}
        </button>
        {granted && (
          <button className="btn" onClick={() => void forget()}>
            Forget them
          </button>
        )}
      </div>
      {granted && (
        <div className="setting">
          <span>Kriko Agent</span>
          <button className="btn" onClick={() => showDrawer('agents')}>Choose agent</button>
        </div>
      )}

      <details className="disclosure">
        <summary>Share your keys with a friend</summary>
        <p className="panel-note" data-kind="data">
          Send the code and the password in two messages. Anyone with both can spend your keys. Replace the keys at the provider to stop a code.
        </p>
        <div className="setting stack">
          <span>Password for them</span>
          <input className="key-field" type="text" autoComplete="off" placeholder="At least 8 characters" aria-label="Password for them" value={madeWith} onChange={(event) => setMadeWith(event.target.value)} />
        </div>
        <div className="setting actions">
          <button className="btn" disabled={madeWith.length < 8} onClick={() => void make(madeWith)}>
            Make an access code
          </button>
        </div>
        {code && (
          <div className="setting stack">
            <span>The code, shown once</span>
            <textarea className="key-field" aria-label="The access code" rows={4} readOnly value={code} onFocus={(event) => event.currentTarget.select()} />
          </div>
        )}
      </details>
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
        <span className="key-name">
          <strong>{label}</strong>
          <span className="state" data-tone={row.present ? 'ok' : 'none'}>
            {row.present ? `Set${row.hint ? `, ends ${row.hint}` : ''}${row.source === 'environment' ? ', from the environment' : ''}` : 'Not set'}
          </span>
        </span>
        {!editing && (
          <span className="key-actions">
            {row.present && <button onClick={onTest}>Test</button>}
            <button onClick={() => setEditing(true)}>{row.present ? 'Change' : 'Add'}</button>
            {row.present && row.source !== 'environment' && <button onClick={onRemove}>Remove</button>}
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
