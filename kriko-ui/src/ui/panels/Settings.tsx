import { useEffect, useState } from 'react'
import { CAP_ORDER, CAP_WORDS, usedToday, useCaps, type CapResource } from '../../engine/caps'
import { useAppUpdate } from '../../engine/appupdate'
import { useSensitivity } from '../../engine/sensitivity'
import { useAbout, useKeys, usePrefsDoc, useSharedAccess, useSpent, type KeyRow } from '../../engine/settings'
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
const SENSITIVITY: { value: Sensitivity; label: string }[] = [
  { value: 'all', label: 'Show everything' },
  { value: 'hide_thin', label: 'Hide thin' },
  { value: 'strict', label: 'Strict' },
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
  const update = useAppUpdate()
  const { sensitivity, choose } = useSensitivity()
  const { caps, setCap } = useCaps()
  const { meters, demo: demoMeters } = useUsage()
  const [sensitivityProblem, setSensitivityProblem] = useState('')
  const [page, setPage] = useState<SettingsPage>(() => takeRequestedSettingsPage() ?? 'look')
  useEffect(() => onSettingsPage(setPage), [])

  return (
    <div className="panel-body">
      {problem && <p className="error-note">{problem}</p>}

      <Segmented label="Settings page" value={page} options={SETTINGS_PAGES} onChange={setPage} />

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
              <span>
                Tour
                <small>A short walk through the window.</small>
              </span>
              <button className="btn" onClick={startTour}>
                Take the tour
              </button>
            </div>
          </section>

          <section className="panel-group">
            <h3>Information sensitivity</h3>
            <div className="setting stack">
              <span>
                How much doubt to show
                <small>
                  A finding is thin when one site alone says it, its best source is low in trust, its quote only partly matches
                  its page, or it depends on a detail your listing does not state. Each card says which. This changes what is
                  drawn, never what is stored.
                </small>
              </span>
              <Segmented
                label="Information sensitivity"
                value={sensitivity}
                options={SENSITIVITY}
                onChange={(value) => void choose(value).then(setSensitivityProblem)}
              />
              <small className="panel-note">
                {sensitivity === 'all' && 'Every finding is drawn, with its indicator.'}
                {sensitivity === 'hide_thin' && 'Findings with two or more reasons for doubt are hidden, and counted so you can show them.'}
                {sensitivity === 'strict' && 'Only findings with no reason for doubt are drawn. The rest are counted.'}
              </small>
              {sensitivityProblem && <p className="error-note">{sensitivityProblem}</p>}
            </div>
          </section>

          <section className="panel-group">
            <h3>Chat</h3>
            <div className="setting">
              <span>
                Chat settings
                <small>What it remembers, and how an answer is shaped.</small>
              </span>
              <button className="btn ghost" onClick={() => showDrawer('chat')}>
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
            <RangeSetting
              label="Thoroughness"
              value={doc.research.thoroughness}
              note="More search calls and results. Applies to Kriko Agent."
              onSave={(value) => void save({ kriko_agent_thoroughness: String(value) })}
            />
            <RangeSetting
              label="Validation sensitivity"
              value={doc.research.validation_sensitivity}
              note="Higher values require longer, exact quotes. Applies to Kriko Agent."
              onSave={(value) => void save({ kriko_agent_validation_sensitivity: String(value) })}
            />
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
          </section>

          <section className="panel-group">
            <h3>Language and market</h3>
            <div className="setting">
              <span>
                Response language
                <small>Automatic follows the product request. Quotes stay in their source language.</small>
              </span>
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
              <span>
                Research language
                <small>Language used to phrase web searches.</small>
              </span>
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
              <span>
                Market region
                <small>Use this market when considering regional products and differences.</small>
              </span>
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
              <span>
                Product classification
                <small>After deterministic checks, use your selected local, coding or API agent by default. Jev is an optional alternative that uses a separate TypeSafe key.</small>
              </span>
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
              <span>
                Set up Kriko
                <small>Verify an agent and connect your browser.</small>
              </span>
              <button className="btn ghost" onClick={() => showDrawer('setup')}>
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
            <p className="panel-note">
              A cap is a warning, not a stop: the usage pill turns amber once a day passes one, and nothing is blocked. Leave a
              field empty for no cap. Caps are kept on this computer.
            </p>
            {CAP_ORDER.map((id) => (
              <CapField
                key={id}
                id={id}
                cap={caps[id]}
                today={usedToday(meters, id)}
                onChange={(value) => setCap(id, value)}
              />
            ))}
            {demoMeters && <p className="panel-note">Example numbers, because no engine answers.</p>}
          </section>

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
              {!!spent.unpriced_runs && <p className="panel-note">{spent.unpriced_runs} runs have incomplete pricing. The amount shown is the measured portion.</p>}
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
                      : update.phase === 'restarting'
                        ? 'Starting the new engine…'
                        : update.phase === 'installing'
                          ? 'Installing. Kriko opens again by itself.'
                          : update.problem ||
                            (update.release ? `Kriko ${update.release.version} is available.` : update.checked ? 'This is the newest version.' : 'Looked for on its own while Kriko is open.')}
                  </small>
                </span>
                {update.release && (update.canInstall || update.release.engine) ? (
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
        </>
      )}
    </div>
  )
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
  const used = today === null ? 'Nothing counted today.' : `${word.money ? `$${today.toFixed(today < 0.01 ? 4 : 2)}` : today.toLocaleString('en-GB')} today.`
  return (
    <div className="setting">
      <span>{word.title} a day<small>{used} {cap === null ? 'No cap set.' : 'A warning only.'}</small></span>
      <label className="cap-field">
        <input type="number" min="0" step={word.money ? '0.01' : '1'} inputMode={word.money ? 'decimal' : 'numeric'} placeholder="No cap" aria-label={`${word.title} a day`} value={draft} onChange={(event) => setDraft(event.target.value)} onBlur={commit} onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur() }} />
        <span className="cap-unit">{word.money ? '$' : word.unit}</span>
      </label>
    </div>
  )
}

function RangeSetting({
  label,
  value,
  note,
  onSave,
}: {
  label: string
  value: number
  note: string
  onSave: (value: number) => void
}) {
  const [draft, setDraft] = useState(value)
  useEffect(() => setDraft(value), [value])
  const commit = () => {
    if (draft !== value) onSave(draft)
  }

  return (
    <div className="setting stack tuning-setting">
      <span>
        {label}
        <small>{note}</small>
      </span>
      <div className="tuning-range-row">
        <small>Low</small>
        <input
          className="tuning-range"
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
        <small>{draft}%</small>
        <small>High</small>
      </div>
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
  // trial are the only two states, so one sentence says which one is in use.
  const fromWhom = doc.grant.label ? `${doc.grant.label}'s keys` : 'shared keys'
  const sharing = granted
    ? `Sharing is on — Kriko Agent can use ${fromWhom}`
    : trial.available
      ? 'Sharing is on — Kriko Agent can use this build’s free trial'
      : 'Sharing is off — Kriko Agent uses the keys saved on this computer'

  return (
    <section className="panel-group" data-tour="shared-access">
      <h3>Shared access</h3>
      <p className="panel-note">
        Kriko Agent on someone else&apos;s Mercury and DeepSeek keys. Paste the access code and the
        password that came with it. The password works in this app only: the code is sealed to the
        build that made it, the keys are never written in the clear, and this app never sends one back.
      </p>
      {problem && <p className="error-note">{problem}</p>}
      {!doc.bound && (
        <p className="panel-note">
          This build carries no share pepper, so a code sealed elsewhere will not open here — and one
          made here would open anywhere. A build for handing out codes needs one:
          <code>python tools/make_share_pepper.py</code>.
        </p>
      )}

      <div className="setting">
        <span>
          {sharing}
          <small>
            {granted
              ? `Mercury and DeepSeek, from an access code, kept sealed on this computer${
                  doc.device === 'dpapi' ? ' and bound to this Windows account' : ''
                }.`
              : trial.available
                ? 'Questions are counted on this computer, on the keys the build carries.'
                : 'Nothing here is shared with anyone: these are the keys you added yourself.'}
          </small>
        </span>
      </div>

      <div className="setting stack">
        <span>
          Access code
          <small>The whole line, from whoever is sharing their keys.</small>
        </span>
        <textarea aria-label="Access code" className="key-field" rows={3} value={pasted} spellCheck={false} placeholder="Paste the code" onChange={(event) => setPasted(event.target.value)} />
      </div>
      <div className="setting stack">
        <span>
          Password
          <small>Sent separately from the code. It is not stored.</small>
        </span>
        <input aria-label="Shared access password" className="key-field" type="password" autoComplete="off" value={password} onChange={(event) => setPassword(event.target.value)} />
      </div>
      <div className="setting stack">
        <span>
          Whose keys
          <small>Optional: a name, so you know what is in use.</small>
        </span>
        <input aria-label="Whose keys" className="key-field" type="text" value={label} onChange={(event) => setLabel(event.target.value)} />
      </div>
      <div className="setting">
        <span>
          Use the keys this code carries
          <small>{granted ? 'Saving replaces the keys in use here.' : 'Saving keeps them sealed on this computer.'}</small>
        </span>
        <span className="key-actions">
          <button className="btn" disabled={saving || !pasted.trim() || !password} onClick={() => void unlockCode()}>
            {saving ? 'Opening code…' : 'Use these keys'}
          </button>
          {granted && (
            <button className="btn ghost" onClick={() => void forget()}>
              Forget them
            </button>
          )}
        </span>
      </div>

      {granted && <p className="panel-note">
        Access is ready. Choose <strong>Kriko Agent</strong> in Agents, then use <strong>Check connection</strong> in Set up Kriko.
        {' '}<button className="btn" onClick={() => showDrawer('agents')}>Choose agent</button>
      </p>}

      <p className="panel-note">
        {granted
          ? ''
          : trial.available
            ? `Free trial on this computer: ${trial.left} of ${trial.limit} Kriko Agent questions left. When they are used up, paste an access code or add your own Mercury and DeepSeek keys in Settings → Keys.`
            : trial.used
              ? `The free trial on this computer is used up (${trial.used} of ${trial.limit} questions). Paste an access code or add your own Mercury and DeepSeek keys in Settings → Keys.`
              : 'No free trial is included in this build.'}
      </p>

      <details className="panel-details">
        <summary>Sharing your own keys with a friend</summary>
        <p className="panel-note">
          Make a code here, then send the code and the password to your friend in two separate
          messages. Anyone with both can use your keys in their Kriko; nothing else can, and a code
          made by a different build will not open in the build they have. To stop a code working,
          replace your Mercury and DeepSeek keys at the providers: nothing here can reach into a
          friend&apos;s computer and take a code back.
        </p>
        <div className="setting stack">
          <span>
            Password for them
            <small>At least 8 characters. It is not stored here or anywhere.</small>
          </span>
          <input className="key-field" type="text" autoComplete="off" value={madeWith} onChange={(event) => setMadeWith(event.target.value)} />
        </div>
        <button className="btn" disabled={madeWith.length < 8} onClick={() => void make(madeWith)}>
          Make an access code
        </button>
        {code && (
          <div className="setting stack">
            <span>
              The code
              <small>Shown here only. Send it without the password.</small>
            </span>
            <textarea className="key-field" rows={4} readOnly value={code} onFocus={(event) => event.currentTarget.select()} />
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
        <span>
          <strong>{label}</strong>
          <small>{row.present ? `Set${row.hint ? ` · ends ${row.hint}` : ''}${row.source === 'environment' ? ' · from the environment' : ''}` : 'Not set'}</small>
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
