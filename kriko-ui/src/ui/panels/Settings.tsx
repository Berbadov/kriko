import { useEffect, useState, type CSSProperties } from 'react'
import { Checkbox } from '../../arc/checkbox/checkbox'
import { CAP_ORDER, CAP_WORDS, usedToday, useCaps, type CapResource } from '../../engine/caps'
import { useAppUpdate } from '../../engine/appupdate'
import { useSensitivity } from '../../engine/sensitivity'
import { useAbout, useKeys, usePrefsDoc, usePresence, useSharedAccess, useSpent, type KeyRow } from '../../engine/settings'
import type { Sensitivity } from '../../engine/thinness'
import { useUsage } from '../../engine/usage'
import { usePrefs, type Profile, type ThemePref } from '../../prefs'
import { startTour } from '../../tour/Tour'
import { Segmented, Select, Switch } from '../controls'
import { showDrawer } from '../drawerEvents'
import { Icon, type IconName } from '../Icon'
import { McpClientsGroup } from './McpClients'
import { ProxiesGroup } from './Proxies'
import { SearchProvidersGroup } from './SearchProviders'
import { SETTINGS_PAGES, onSettingsPage, takeRequestedSettingsPage, type SettingsPage } from './settingsPages'
import { Group, Hint, IconButton, IconChoice, LevelIcon, LockIcon, MoonIcon, Row, State, SunIcon, type IconOption } from './settingsParts'

/** The page list: an icon for each, and the chosen one says its name. */
const PAGE_ICONS: Record<SettingsPage, IconName> = {
  look: 'palette',
  research: 'search',
  keys: 'key',
  connections: 'plug',
  usage: 'chart',
  about: 'info',
}
const PAGE_OPTIONS: IconOption<SettingsPage>[] = SETTINGS_PAGES.map((page) => ({ value: page.value, label: page.label, icon: <Icon name={PAGE_ICONS[page.value]} size={20} /> }))

const THEMES: IconOption<ThemePref>[] = [
  { value: 'system', label: 'System', icon: <Icon name="monitor" size={22} /> },
  { value: 'dark', label: 'Dark', icon: <MoonIcon /> },
  { value: 'light', label: 'Light', icon: <SunIcon /> },
]
const PROFILES: IconOption<Profile>[] = [
  { value: 'calm', label: 'Calm', icon: <LevelIcon level={1} /> },
  { value: 'standard', label: 'Standard', icon: <LevelIcon level={2} /> },
  { value: 'vivid', label: 'Vivid', icon: <LevelIcon level={3} /> },
]
/** What each choice does is in its tooltip, after its name. */
const SENSITIVITY: IconOption<Sensitivity>[] = [
  { value: 'all', label: 'Show everything', hint: 'Every finding is drawn, with its indicator.', icon: <Icon name="eye" size={22} /> },
  { value: 'hide_thin', label: 'Hide thin', hint: 'Findings with two or more reasons for doubt are hidden, and counted so you can show them.', icon: <Icon name="eyeoff" size={22} /> },
  { value: 'strict', label: 'Strict', hint: 'Only findings with no reason for doubt are drawn. The rest are counted.', icon: <Icon name="shieldcheck" size={22} /> },
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
const KIND_ICONS: Record<string, IconName> = {
  forums: 'chat',
  reviews: 'star',
  recalls: 'alert',
  manufacturer: 'building',
  video: 'video',
  news: 'news',
}
const CAP_ICONS: Record<CapResource, IconName> = {
  cli_agent: 'cpu',
  llm_api: 'coins',
  web_search: 'search',
  local_model: 'server',
}

/** Look, research, keys, connections, and usage. One page is drawn at a time, so
 *  the drawer is a short list of choices instead of one long scroll. */
export function SettingsPanel(_: { onOpen?: (lookupId: string) => void }) {
  const { theme, setTheme, profile, setProfile, reduce, setReduce } = usePrefs()
  const { doc, problem, save } = usePrefsDoc()
  const spent = useSpent()
  const { sensitivity, choose } = useSensitivity()
  const { caps, setCap } = useCaps()
  const { meters, demo: demoMeters } = useUsage()
  const [sensitivityProblem, setSensitivityProblem] = useState('')
  const [page, setPage] = useState<SettingsPage>(() => takeRequestedSettingsPage() ?? 'look')
  useEffect(() => onSettingsPage(setPage), [])

  return (
    <div className="panel-body settings">
      <div className="settings-nav">
        <IconChoice tabs side="bottom" label="Settings page" value={page} options={PAGE_OPTIONS} onChange={setPage} />
      </div>
      {problem && <p className="error-note">{problem}</p>}

      <div className="settings-page" key={page}>
      {page === 'look' && (
        <>
          <Group icon="palette" title="Look">
            <Row icon="palette" label="Theme">
              <IconChoice label="Theme" value={theme} options={THEMES} onChange={setTheme} />
            </Row>
            <Row icon="gauge" label="Motion">
              <IconChoice label="Motion" value={profile} options={PROFILES} onChange={setProfile} />
            </Row>
            <Row icon="pause" label="Reduce motion">
              <Switch label="Reduce motion" on={reduce} onChange={setReduce} />
            </Row>
            <Row icon="compass" label="Tour">
              <IconButton icon="play" label="Take the tour" onClick={startTour} />
            </Row>
          </Group>

          <Group icon="eye" title="Findings">
            <Row icon="shield" label="Doubt">
              <IconChoice label="Information sensitivity" value={sensitivity} options={SENSITIVITY} onChange={(value) => void choose(value).then(setSensitivityProblem)} />
            </Row>
            {sensitivityProblem && <p className="error-note">{sensitivityProblem}</p>}
          </Group>

          <Group icon="chat" title="Chat">
            <Row icon="chat" label="Chat settings">
              <IconButton icon="expand" label="Open chat settings" onClick={() => showDrawer('chat')} />
            </Row>
          </Group>
        </>
      )}

      {page === 'research' && doc && (
        <>
          <Group icon="gauge" title="Effort">
            <Row icon="layers" label="At once">
              <Segmented label="Products at once" value={doc.chosen.run_concurrency || '4'} options={PARALLEL} onChange={(value) => void save({ run_concurrency: value })} />
            </Row>
            <RangeSetting
              icon="search"
              label="Thoroughness"
              value={doc.research.thoroughness}
              cost="Higher means more search calls."
              onSave={(value) => void save({ kriko_agent_thoroughness: String(value) })}
            />
            <RangeSetting
              icon="shieldcheck"
              label="Validation"
              value={doc.research.validation_sensitivity}
              onSave={(value) => void save({ kriko_agent_validation_sensitivity: String(value) })}
            />
            <Row icon="docplus" label="Extra sources">
              <Select
                label="Extra sources"
                value={String(doc.research.sources)}
                options={(SOURCE_COUNTS.includes(doc.research.sources) ? SOURCE_COUNTS : [doc.research.sources, ...SOURCE_COUNTS]).map((n) => ({ value: String(n), label: String(n) }))}
                onChange={(value) => void save({ research_sources: value })}
              />
            </Row>
            <Row icon="globe" label="Where to look" stack tour="source-kinds">
              <div className="choices">
                {doc.source_kinds.map((kind) => {
                  const on = doc.research.kinds.includes(kind.id)
                  return (
                    <button
                      key={kind.id}
                      type="button"
                      className="choice"
                      role="checkbox"
                      aria-checked={on}
                      data-on={on}
                      onClick={() => {
                        const kinds = !on ? [...doc.research.kinds, kind.id] : doc.research.kinds.filter((id) => id !== kind.id)
                        // One kind has to stay, or research has nowhere to look.
                        if (kinds.length) void save({ research_source_kinds: kinds.join(',') })
                      }}
                    >
                      <Icon name={KIND_ICONS[kind.id] ?? 'globe'} size={18} />
                      {KIND_NAMES[kind.id] ?? kind.id}
                    </button>
                  )
                })}
              </div>
            </Row>
          </Group>

          <Group icon="globe" title="Region">
            <Row icon="chat" label="Reply in">
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
            </Row>
            <Row icon="search" label="Search in">
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
            </Row>
            <Row icon="pin" label="Market">
              <Select
                label="Market region"
                value={doc.chosen.market_region || 'auto'}
                options={doc.market_regions.map((region) => ({ value: region.id, label: region.label }))}
                onChange={(value) => void save({ market_region: value })}
              />
            </Row>
          </Group>

          <Group icon="cube" title="Model">
            <Row icon="tag" label="Classify">
              <Select
                label="Product classification"
                value={doc.chosen.classification_provider || 'agent'}
                options={doc.classification_providers.map((provider) => ({
                  value: provider.id,
                  label: provider.ready ? provider.label : `${provider.label} (no key)`,
                }))}
                onChange={(value) => void save({ classification_provider: value })}
              />
            </Row>
            <Row icon="link" label="Endpoint" stack>
              <EndpointField value={doc.chosen.llm_base_url || ''} onSave={(value) => save({ llm_base_url: value })} />
            </Row>
            <Row icon="cube" label="Model name" stack>
              <ModelField value={doc.chosen.llm_model || ''} onSave={(value) => save({ llm_model: value })} />
            </Row>
          </Group>
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
          <Group icon="gear" title="Setup">
            <Row icon="gear" label="Set up Kriko">
              <IconButton icon="expand" label="Open setup" onClick={() => showDrawer('setup')} />
            </Row>
          </Group>

          <SearchProvidersGroup />

          <ProxiesGroup />

          <McpClientsGroup />
        </>
      )}

      {page === 'usage' && (
        <>
          <Group
            icon="chart"
            title="Caps"
            hint={
              <>
                {demoMeters && <State tone="warn" icon="alert">Example numbers</State>}
                <Hint icon="coins" title="A cap only warns">A cap only warns. Nothing is blocked.</Hint>
              </>
            }
          >
            {CAP_ORDER.map((id) => (
              <CapField
                key={id}
                id={id}
                cap={caps[id]}
                today={usedToday(meters, id)}
                onChange={(value) => setCap(id, value)}
              />
            ))}
          </Group>

          {spent && (
            <Group
              icon="coins"
              title="Spent"
              hint={
                <>
                  <State>{spent.days} days</State>
                  {!!spent.unpriced_runs && (
                    <Hint icon="coins" title="Partial price" tone="warn">
                      {spent.unpriced_runs} runs have no price, so the amount is partial.
                    </Hint>
                  )}
                </>
              }
            >
              <div className="tiles">
                <div>
                  <Icon name="play" size={18} />
                  <strong>{spent.runs}</strong>
                  <small>runs</small>
                </div>
                <div>
                  <Icon name="layers" size={18} />
                  <strong>{spent.tokens >= 1000 ? `${Math.round(spent.tokens / 1000)}k` : spent.tokens}</strong>
                  <small>tokens</small>
                </div>
                <div>
                  <Icon name="coins" size={18} />
                  <strong>${spent.usd.toFixed(2)}</strong>
                  <small>spend</small>
                </div>
              </div>
            </Group>
          )}

        </>
      )}

      {page === 'about' && <AboutPage />}
      </div>
    </div>
  )
}

/** Version, updates and what this copy sends home: its own page, apart from usage.
 *  The Updates entry in the More menu opens the same page. */
export function AboutPage(_: { onOpen?: (lookupId: string) => void } = {}) {
  const { doc, save } = usePrefsDoc()
  const about = useAbout()
  const { presence, reload: reloadPresence } = usePresence()
  const update = useAppUpdate()
  return (
    <div className="about-page">
          {about && (
            <Group icon="info" title="Version and updates">
              <Row icon="cpu" label="Engine">
                <span className="value">{about.version || 'Not known'}</span>
              </Row>
              <Row icon="download" label="Updates" state={updateState(update) ? <State tone={update.release ? 'ok' : 'none'}>{updateState(update)}</State> : undefined}>
                {update.release && (update.canInstall || update.release.engine) ? (
                  <button className="btn primary" onClick={() => void update.install()} disabled={update.phase !== 'idle'}>
                    <Icon name="download" size={18} />
                    Update
                  </button>
                ) : (
                  <IconButton icon="retry" label={update.phase === 'checking' ? 'Checking for updates' : 'Check for updates'} onClick={() => void update.check()} disabled={update.phase !== 'idle'} />
                )}
              </Row>
              {update.problem && update.phase === 'idle' && <p className="error-note">{update.problem}</p>}
              <Row icon="folder" label="Your data">
                <span className="value path">{about.folder || 'Not known'}</span>
              </Row>
            </Group>
          )}
          {presence && (
            <Group
              icon="bell"
              title="Ping"
              hint={
                <Hint icon="cloudup" title="What the ping sends">
                  Once a day: a random install id and the app version, nothing else. Read the <a href="https://kriko.cc/privacy/">privacy policy</a>.
                  {!presence.endpoint && ' No endpoint is set, so nothing leaves this computer.'}
                </Hint>
              }
            >
              <Row icon="bell" label="Daily ping">
                <Switch
                  label="Anonymous daily ping"
                  on={doc?.chosen.presence_enabled === '1' || presence.enabled}
                  onChange={(on) => void save({ presence_enabled: on ? '1' : '0' }).then(() => void reloadPresence())}
                />
              </Row>
              {(doc?.chosen.presence_enabled === '1' || presence.enabled) && (
                <Row icon="clock" label="Last sent">
                  <span className="value">{presence.last_day || 'On the next start'}</span>
                </Row>
              )}
            </Group>
          )}
          {doc && (
            <Group
              icon="shieldcheck"
              title="Product queries"
              hint={
                <Hint icon="cloudup" title="What is shared">
                  Only the product model you looked up and whether our catalog had it. Read the <a href="https://kriko.cc/privacy/">privacy policy</a>.
                </Hint>
              }
            >
              <Row icon="search" label="Share" stack>
                <Checkbox
                  checked={doc.chosen.share_queries === '1'}
                  onCheckedChange={(on) => void save({ share_queries: on === true ? '1' : '0' })}
                  label="Share my product queries"
                  description={'When on, Kriko sends the product model you looked up (for example "Brand Model 128GB") and whether our catalog had it, so we know which products to cover next. It never sends the listing link, the page title, the time, or anything that identifies you or your device. Off by default.'}
                />
              </Row>
            </Group>
          )}

    </div>
  )
}

/** The one short state an update row shows beside its name. A problem is its own line. */
function updateState(update: ReturnType<typeof useAppUpdate>): string {
  if (update.phase === 'downloading') return 'Downloading…'
  if (update.phase === 'restarting') return 'Starting…'
  if (update.phase === 'installing') return 'Installing'
  if (update.problem) return ''
  if (update.release) return `Kriko ${update.release.version}`
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
    <Row icon={CAP_ICONS[id]} label={word.title} state={used ? <State>{used}</State> : undefined}>
      <label className="cap-field">
        <input type="number" min="0" step={word.money ? '0.01' : '1'} inputMode={word.money ? 'decimal' : 'numeric'} placeholder="No cap" aria-label={`${word.title} a day`} value={draft} onChange={(event) => setDraft(event.target.value)} onBlur={commit} onKeyDown={(event) => { if (event.key === 'Enter') event.currentTarget.blur() }} />
        <span className="cap-unit">{word.money ? '$' : word.unit}/day</span>
      </label>
    </Row>
  )
}

/** A dial from 0 to 100: its name and value on one line, the slider under them.
 *  `cost` is for a dial that costs money: a coin that says so on hover. */
function RangeSetting({
  icon,
  label,
  value,
  cost,
  onSave,
}: {
  icon: IconName
  label: string
  value: number
  cost?: string
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
        <span className="row-label">
          <span className="row-icon" aria-hidden="true">
            <Icon name={icon} size={20} />
          </span>
          <span className="row-name">{label}</span>
          {cost && (
            <Hint icon="coins" title="Costs more">
              {cost}
            </Hint>
          )}
        </span>
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
    <Group
      icon="key"
      title="Keys"
      hint={
        <Hint icon="shield" title="Keys stay here">
          Keys stay on this computer. The engine never sends one back.
        </Hint>
      }
    >
      {problem && <p className="error-note">{problem}</p>}
      <ul className="key-list">
        {doc.providers.map((row) => (
          <KeyItem key={row.id} row={row} result={tested[row.id] ?? ''} onSave={(value) => set(row.id, value)} onRemove={() => void remove(row.id)} onTest={() => void test(row.id)} />
        ))}
      </ul>
    </Group>
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
    ? `${trial.left} of ${trial.limit} left`
    : trial.used
      ? `Used up, ${trial.used} of ${trial.limit}`
      : 'Not in this build'

  return (
    <Group
      icon="users"
      title="Sharing"
      tour="shared-access"
      hint={
        <>
          {!doc.bound && (
            <Hint icon="alert" tone="warn" title="No share pepper">
              This build has no share pepper, so a code made elsewhere will not open here. Build one with <code>python tools/make_share_pepper.py</code>.
            </Hint>
          )}
          <Hint icon="lock" title="Password scope">
            The password works in this app only. Keys are sealed on this computer.
          </Hint>
        </>
      }
    >
      {problem && <p className="error-note">{problem}</p>}

      <Row icon="users" label="Sharing">
        <span className="setting-end">
          <State tone={granted || trial.available ? 'ok' : 'none'}>{sharing}</State>
          {granted && doc.device === 'dpapi' && <State icon="lock">Windows account</State>}
        </span>
      </Row>
      {!granted && (
        <Row
          icon="spark"
          label="Free trial"
          hint={
            !trial.available && trial.used > 0 ? (
              <Hint icon="alert" tone="warn" title="Trial used up">
                Paste an access code or add your own keys on this page.
              </Hint>
            ) : undefined
          }
        >
          <span className="value">{trialState}</span>
        </Row>
      )}

      <Row icon="key" label="Access code" stack>
        <textarea aria-label="Access code" className="key-field" rows={3} value={pasted} spellCheck={false} placeholder="Paste the code" onChange={(event) => setPasted(event.target.value)} />
      </Row>
      <Row icon="lock" label="Password" stack>
        <input aria-label="Shared access password" className="key-field" type="password" autoComplete="off" placeholder="Sent apart from the code" value={password} onChange={(event) => setPassword(event.target.value)} />
      </Row>
      <Row icon="users" label="Whose keys" stack>
        <input aria-label="Whose keys" className="key-field" type="text" placeholder="Optional" value={label} onChange={(event) => setLabel(event.target.value)} />
      </Row>
      <Row actions>
        {granted && (
          <button className="btn" onClick={() => void forget()}>
            <Icon name="trash" size={18} />
            Forget
          </button>
        )}
        <button className="btn primary" disabled={saving || !pasted.trim() || !password} onClick={() => void unlockCode()}>
          <Icon name="check" size={18} />
          {saving ? 'Opening…' : 'Use keys'}
        </button>
      </Row>
      {granted && (
        <Row icon="cpu" label="Agent">
          <IconButton icon="expand" label="Choose agent" onClick={() => showDrawer('agents')} />
        </Row>
      )}

      <details className="disclosure">
        <summary>
          <span className="row-label">
            <span className="row-icon" aria-hidden="true">
              <Icon name="cloudup" size={20} />
            </span>
            <span className="row-name">Share your keys</span>
          </span>
        </summary>
        <Row
          icon="lock"
          label="Password for them"
          stack
          hint={
            <Hint icon="alert" tone="warn" title="Who can spend your keys">
              Send the code and the password in two messages. Anyone with both can spend your keys. Replace the keys at the provider to stop a code.
            </Hint>
          }
        >
          <input className="key-field" type="text" autoComplete="off" placeholder="At least 8 characters" aria-label="Password for them" value={madeWith} onChange={(event) => setMadeWith(event.target.value)} />
        </Row>
        <Row actions>
          <button className="btn" disabled={madeWith.length < 8} onClick={() => void make(madeWith)}>
            <Icon name="plus" size={18} />
            Make code
          </button>
        </Row>
        {code && (
          <Row icon="key" label="The code" stack>
            <textarea className="key-field" aria-label="The access code" rows={4} readOnly value={code} onFocus={(event) => event.currentTarget.select()} />
          </Row>
        )}
      </details>
    </Group>
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
          <span className="row-icon" data-tone={row.present ? 'ok' : undefined} aria-hidden="true">
            <LockIcon locked={row.present} />
          </span>
          <strong>{label}</strong>
          <State tone={row.present ? 'ok' : 'none'}>
            {row.present ? `${row.hint ? `ends ${row.hint}` : 'Set'}${row.source === 'environment' ? ', from the environment' : ''}` : 'Not set'}
          </State>
        </span>
        {!editing && (
          <span className="key-actions">
            {row.present && <IconButton icon="play" label={`Test ${label} key`} onClick={onTest} />}
            <IconButton icon={row.present ? 'edit' : 'plus'} label={`${row.present ? 'Change' : 'Add'} ${label} key`} onClick={() => setEditing(true)} />
            {row.present && row.source !== 'environment' && <IconButton icon="trash" label={`Remove ${label} key`} tone="danger" onClick={onRemove} />}
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
          <IconButton type="submit" icon="check" label={`Save ${label} key`} tone="primary" disabled={!value.trim()} />
          <IconButton
            icon="x"
            label="Cancel"
            onClick={() => {
              setValue('')
              setEditing(false)
            }}
          />
        </form>
      )}
      {result && <small className="key-result">{result}</small>}
    </li>
  )
}
