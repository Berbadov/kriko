import { useState, type FormEvent } from 'react'
import { useAppUpdate } from '../../engine/appupdate'
import { useAbout, useKeys, usePrefsDoc, usePresence, useSharedAccess, type KeyRow } from '../../engine/settings'
import { showDrawer } from '../drawerEvents'
import { Icon } from '../Icon'
import { Actions, Group, Hint, IconButton, Row, Section, Setting, State, Switch, Toggle } from '../panels/settingsParts'

/** The Keys and models section's pieces: provider keys, shared access (with the
 *  product-query opt-in), the model endpoint and name, and the about block the
 *  Data section draws. Every save goes through the same prefs keys and engine
 *  calls as before. */

/** The one short state an update row shows beside its name. A problem is its own line. */
function updateState(update: ReturnType<typeof useAppUpdate>): string {
  if (update.phase === 'downloading') return 'Downloading…'
  if (update.phase === 'restarting') return 'Starting…'
  if (update.phase === 'installing') return 'Installing'
  if (update.problem) return ''
  if (update.release) return `Kriko ${update.release.version}`
  return update.checked ? 'Up to date' : ''
}

/** A password-style field. The text stays hidden until the reader presses the
 *  word beside it, which says what the press does. */
export function SecretField({ name, value, onChange, placeholder, autoComplete = 'off' }: { name: string; value: string; onChange: (value: string) => void; placeholder?: string; autoComplete?: string }) {
  const [shown, setShown] = useState(false)
  return (
    <span className="keys-secret">
      <input
        className="k-input"
        type={shown ? 'text' : 'password'}
        autoComplete={autoComplete}
        spellCheck={false}
        placeholder={placeholder}
        aria-label={name}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
      <button type="button" className="k-btn" data-size="sm" aria-label={`${shown ? 'Hide' : 'Show'} ${name}`} onClick={() => setShown((now) => !now)}>
        {shown ? 'Hide' : 'Show'}
      </button>
    </span>
  )
}

/** The saved provider keys, one row each: set or not, what it is for, a field to
 *  type a key into, Save, and Test and Remove once a key is set. */
export function KeysGroup() {
  const { doc, problem, tested, set, remove, test } = useKeys()
  if (!doc) return null
  return (
    <Section title="Provider keys" note="Keys stay on this computer. The engine never sends one back.">
      {problem && <p className="error-note">{problem}</p>}
      {doc.providers.map((row) => (
        <KeyItem key={row.id} row={row} result={tested[row.id] ?? ''} onSave={(value) => set(row.id, value)} onRemove={() => void remove(row.id)} onTest={() => void test(row.id)} />
      ))}
    </Section>
  )
}

function KeyItem({ row, result, onSave, onRemove, onTest }: { row: KeyRow; result: string; onSave: (value: string) => Promise<void>; onRemove: () => void; onTest: () => void }) {
  const [value, setValue] = useState('')
  const label = row.label.replace(/ \(.*\)$/, '')
  const fromEnvironment = row.source === 'environment'
  const note = [row.purpose, fromEnvironment && "It comes from this computer's environment, so it can only be changed there."].filter(Boolean).join(' ')

  const submit = async () => {
    if (!value.trim()) return
    await onSave(value)
    setValue('')
  }

  return (
    <Setting
      icon={row.present ? 'lock' : 'unlock'}
      label={label}
      value={<State tone={row.present ? 'ok' : 'none'}>{row.present ? 'Set' : 'Not set'}</State>}
      note={note}
      stack
      control={
        <form
          className="keys-stack"
          onSubmit={(event: FormEvent) => {
            event.preventDefault()
            void submit()
          }}
        >
          <SecretField name={`${label} key`} value={value} onChange={setValue} placeholder={row.present ? 'Paste a new key to replace it' : `Paste your ${label} key`} />
          <span className="keys-actions">
            <button type="submit" className="k-btn" data-kind="primary" aria-label={`Save ${label} key`} disabled={!value.trim()}>
              Save
            </button>
            {row.present && (
              <button type="button" className="k-btn" aria-label={`Test ${label} key`} onClick={onTest}>
                Test
              </button>
            )}
            {row.present && !fromEnvironment && (
              <button type="button" className="k-btn" data-kind="danger" aria-label={`Remove ${label} key`} onClick={onRemove}>
                Remove
              </button>
            )}
          </span>
          {result && (
            <small className="keys-result" role="status">
              {result}
            </small>
          )}
        </form>
      }
    />
  )
}

/** Use someone else's keys for Kriko Agent, or hand a friend a password for yours.
 *  Also the opt-in to share which product queries leave this computer. */
export function SharedAccessGroup() {
  const { doc, problem, code, unlock, forget, make } = useSharedAccess()
  const prefs = usePrefsDoc()
  const [pasted, setPasted] = useState('')
  const [password, setPassword] = useState('')
  const [label, setLabel] = useState('')
  const [madeWith, setMadeWith] = useState('')
  const [saving, setSaving] = useState(false)
  const unlockCode = async () => {
    setSaving(true)
    try {
      if (await unlock(pasted, password, label)) {
        setPassword('')
        setPasted('')
      }
    } finally {
      setSaving(false)
    }
  }
  if (!doc) return null
  const trial = doc.trial
  const granted = doc.grant.present
  // Whether Kriko Agent is answering on somebody else's keys here. Every number
  // below is the engine's own (`/api/keys/shared/status`).
  const fromWhom = doc.grant.label ? `${doc.grant.label}'s keys` : 'shared keys'
  const sharing = granted ? `On, ${fromWhom}` : trial.available ? 'On, free trial' : 'Off, your own keys'
  const trialState = trial.available ? `${trial.left} of ${trial.limit} left` : trial.used ? `Used up, ${trial.used} of ${trial.limit}` : 'Not in this build'
  const shares = prefs.doc?.chosen.share_queries === '1'

  return (
    <>
      <Section
        title="Shared access"
        note={
          <>
            {!doc.bound && (
              <Hint tone="warn">
                This build has no share pepper, so a code made elsewhere will not open here. Build one with <code>python tools/make_share_pepper.py</code>.
              </Hint>
            )}
            <Hint>The password works in this app only. Keys are sealed on this computer.</Hint>
          </>
        }
      >
        {problem && <p className="error-note">{problem}</p>}

        <Setting
          icon="users"
          label="Access"
          note={granted ? 'The keys Kriko Agent answers with right now.' : 'The keys Kriko Agent answers with right now, until you add a code.'}
          state={granted && doc.device === 'dpapi' ? <State icon="lock">Windows account</State> : undefined}
          value={<State tone={granted || trial.available ? 'ok' : 'none'}>{sharing}</State>}
        />
        {!granted && (
          <Setting
            icon="spark"
            label="Free trial"
            value={trialState}
            note={
              !trial.available && trial.used > 0 ? (
                <Hint tone="warn">Paste an access code or add your own keys on this page.</Hint>
              ) : (
                'A few Kriko Agent questions to try it before you have a code. Shown only when this build offers them.'
              )
            }
          />
        )}

        <Setting
          icon="key"
          label="Paste the access code"
          stack
          note="A long code a friend sends you. It opens nothing without the password."
          control={<textarea aria-label="Access code" className="k-input settings-field" rows={3} value={pasted} spellCheck={false} placeholder="Paste the code" onChange={(event) => setPasted(event.target.value)} />}
        />
        <Setting
          icon="lock"
          label="Paste the password"
          stack
          note="It comes in a separate message from the code, on purpose: one message on its own opens nothing."
          control={<SecretField name="Shared access password" value={password} onChange={setPassword} placeholder="Sent apart from the code" />}
        />
        <Setting
          icon="users"
          label="Whose keys"
          stack
          note="Optional. A name to remember whose keys these are."
          control={<input aria-label="Whose keys" className="k-input settings-field" type="text" placeholder="Optional" value={label} onChange={(event) => setLabel(event.target.value)} />}
        />
        <Actions>
          {granted && (
            <button type="button" className="k-btn" onClick={() => void forget()}>
              <Icon name="trash" size={16} />
              Forget
            </button>
          )}
          <button type="button" className="k-btn" data-kind="primary" disabled={saving || !pasted.trim() || !password} onClick={() => void unlockCode()}>
            <Icon name="check" size={16} />
            {saving ? 'Opening…' : 'Use keys'}
          </button>
        </Actions>
        {granted && <Setting icon="cpu" label="Agent" note="The agent that uses these keys." control={<IconButton icon="expand" label="Choose agent" onClick={() => showDrawer('agents')} />} />}

        {prefs.doc && (
          <Setting
            icon="cloudup"
            label="Share product queries"
            note="Sends the product model you looked up and whether our catalog had it. It never sends the listing link, the page title, the time, or anything about you or your device. Off by default."
            control={<Toggle label="Share my product queries" on={shares} onChange={(on) => void prefs.save({ share_queries: on ? '1' : '0' })} />}
          />
        )}
      </Section>

      <details className="settings-fold">
        <summary>Share your keys</summary>
        <Setting
          icon="lock"
          label="Password for them"
          stack
          note={<Hint tone="warn">Send the code and the password in two messages. Anyone with both can spend your keys. Replace the keys at the provider to stop a code.</Hint>}
          control={
            <div className="keys-stack">
              <input className="k-input settings-field" type="text" autoComplete="off" placeholder="At least 8 characters" aria-label="Password for them" value={madeWith} onChange={(event) => setMadeWith(event.target.value)} />
              <span className="keys-actions">
                <button type="button" className="k-btn" disabled={madeWith.length < 8} onClick={() => void make(madeWith)}>
                  <Icon name="plus" size={16} />
                  Make code
                </button>
              </span>
            </div>
          }
        />
        {code && (
          <Setting
            icon="key"
            label="The code"
            stack
            note="Shown once. Send it with the password, in another message."
            control={<textarea className="k-input settings-field" aria-label="The access code" rows={4} readOnly value={code} onFocus={(event) => event.currentTarget.select()} />}
          />
        )}
      </details>
    </>
  )
}

/** The model the endpoint answers with: the address and the name, each saved when
 *  the reader leaves the field. The same fields Research drew before. */
export function ModelGroup() {
  const { doc, save } = usePrefsDoc()
  if (!doc) return null
  return (
    <Section title="Model">
      <Setting
        icon="link"
        label="Endpoint"
        stack
        note="An address that speaks the OpenAI protocol, used for model calls. Leave it empty to use the default."
        control={<EndpointField value={doc.chosen.llm_base_url || ''} onSave={(value) => save({ llm_base_url: value })} />}
      />
      <Setting icon="cube" label="Model name" stack note="The model the endpoint should answer with." control={<ModelField value={doc.chosen.llm_model || ''} onSave={(value) => save({ llm_model: value })} />} />
    </Section>
  )
}

/** The endpoint. Saved without a trailing slash, and only when it changed. */
export function EndpointField({ value, onSave }: { value: string; onSave: (value: string) => Promise<void> }) {
  const [draft, setDraft] = useState(value)
  const [seen, setSeen] = useState(value)
  // A saved value that changed elsewhere replaces the draft, without an effect.
  if (value !== seen) {
    setSeen(value)
    setDraft(value)
  }
  return (
    <input
      className="k-input"
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

/** The model name. Trimmed, and saved only when it changed. */
export function ModelField({ value, onSave }: { value: string; onSave: (value: string) => Promise<void> }) {
  const [draft, setDraft] = useState(value)
  const [seen, setSeen] = useState(value)
  // A saved value that changed elsewhere replaces the draft, without an effect.
  if (value !== seen) {
    setSeen(value)
    setDraft(value)
  }
  return (
    <input
      className="k-input"
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

/** Version, updates, what this copy sends home, and where the data lives. */
export function AboutPage() {
  const { doc, save } = usePrefsDoc()
  const about = useAbout()
  const { presence, reload: reloadPresence } = usePresence()
  const update = useAppUpdate()
  return (
    <>
      {about && (
        <Group title="Version and updates">
          <Row icon="cpu" label="Engine">
            <span className="value">{about.version || 'Not known'}</span>
          </Row>
          <Row icon="download" label="Updates" state={updateState(update) ? <State tone={update.release ? 'ok' : 'none'}>{updateState(update)}</State> : undefined}>
            {update.release && (update.canInstall || update.release.engine) ? (
              <button type="button" className="k-btn" data-kind="primary" onClick={() => void update.install()} disabled={update.phase !== 'idle'}>
                <Icon name="download" size={16} />
                Update
              </button>
            ) : (
              <IconButton icon="retry" label={update.phase === 'checking' ? 'Checking for updates' : 'Check for updates'} onClick={() => void update.check()} disabled={update.phase !== 'idle'}>
                {update.phase === 'checking' ? 'Checking…' : 'Check for updates'}
              </IconButton>
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
          title="Ping"
          hint={
            <Hint>
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
    </>
  )
}

