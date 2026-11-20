import { useEffect, useState, type ReactNode } from 'react'
import { get, post } from '../../engine/api'
import { followJob } from '../../engine/jobs'
import { useEngine } from '../../engine/Engine'
import { showDrawer } from '../drawerEvents'
import { ExternalLink } from '../ExternalLink'
import { showSettingsPage } from './settingsPages'
import { Section, Setting, State } from './settingsParts'

type Extension = { connected: boolean; staged: boolean; path: string; ever_connected: boolean }

/** The published listing. A reader installs from here; a checkout still has the folder. */
const STORE = 'https://chromewebstore.google.com/detail/kriko/bdifnaggafjokndlpjgmlfappcoehdjb'

/** A word on a press. Every control in a row says what it does. */
function Press({ tone, disabled, onClick, children }: { tone?: 'primary' | 'quiet'; disabled?: boolean; onClick?: () => void; children: ReactNode }) {
  return (
    <button type="button" className="k-btn" data-kind={tone} disabled={disabled} onClick={onClick}>
      {children}
    </button>
  )
}

/** The set-up checklist: four steps in order, each with a state and one word press.
 *  A step is Done only when Kriko can see that it is; the last step has no signal,
 *  so it stays To do until the reader has tried a sourced check. */
export function SetupGroup() {
  const { mode } = useEngine()
  const [extension, setExtension] = useState<Extension | null>(null)
  const [catalogs, setCatalogs] = useState<number | null>(null)
  const [status, setStatus] = useState('')
  const [working, setWorking] = useState(false)
  const [verified, setVerified] = useState(false)
  const reload = async () => {
    try {
      const [browser, packs] = await Promise.all([get<Extension>('/api/extension'), get<unknown[]>('/api/packs')])
      setExtension(browser); setCatalogs(packs.length)
    } catch (error) { setStatus(error instanceof Error ? error.message : 'Could not check setup.') }
  }
  useEffect(() => {
    if (mode !== 'live') return
    let active = true
    Promise.all([get<Extension>('/api/extension'), get<unknown[]>('/api/packs')]).then(
      ([browser, packs]) => { if (active) { setExtension(browser); setCatalogs(packs.length) } },
      (error: unknown) => { if (active) setStatus(error instanceof Error ? error.message : 'Could not check setup.') },
    )
    return () => { active = false }
  }, [mode])

  const verify = async () => {
    setWorking(true); setStatus('Asking the selected agent to verify its connection…')
    try {
      const sent = await post<{job_id: string}>('/api/agents/check', {})
      const ended = await followJob(sent.job_id, (reading) => setStatus(reading.message || 'Checking connection…'))
      if (ended?.state !== 'succeeded') throw new Error(ended?.message || 'The connection check failed.')
      setVerified(true); setStatus('The selected agent answered. Next, ask for a sourced product check to verify research.')
    } catch (error) { setStatus(error instanceof Error ? error.message : 'The agent did not answer.') }
    finally { setWorking(false) }
  }
  const stage = async () => {
    setWorking(true)
    try { await post('/api/extension/stage', {}); await reload(); setStatus('Extension prepared. Load the folder below in your browser.') }
    catch (error) { setStatus(error instanceof Error ? error.message : 'Could not prepare the extension.') }
    finally { setWorking(false) }
  }

  const agentDone = verified
  const catalogsDone = catalogs !== null && catalogs > 0
  const browserDone = Boolean(extension?.connected)
  const steps = [agentDone, catalogsDone, browserDone, false]
  // One blue press per view: it goes to the first step not yet done.
  const next = steps.indexOf(false)
  const primary = (index: number) => (next === index ? 'primary' : 'quiet')

  return (
    <>
      <Section
        title="Browser extension and set-up"
        aside={<State tone={steps.every(Boolean) ? 'ok' : undefined}>{steps.filter(Boolean).length} of {steps.length} done</State>}
        note="Four steps, in order. Kriko marks a step done only when it can see that it is."
      >
        <Setting
          label="Choose who does the research"
          note="An installed agent does the research, so it needs a working account and model. Check that it answers."
          state={<State tone={agentDone ? 'ok' : undefined}>{agentDone ? 'Done' : 'To do'}</State>}
          control={
            <>
              <Press tone="quiet" onClick={() => showDrawer('agents')}>Choose agent</Press>
              <Press tone={primary(0)} disabled={working || mode !== 'live'} onClick={() => void verify()}>Check connection</Press>
            </>
          }
        />
        <Setting
          label="Add product knowledge"
          note="A catalog holds what is known about one kind of product. Research can also read public sources for a new product."
          value={catalogs === null ? undefined : `${catalogs} installed`}
          state={<State tone={catalogsDone ? 'ok' : undefined}>{catalogsDone ? 'Done' : 'To do'}</State>}
          control={<Press tone={primary(1)} onClick={() => showDrawer('browse')}>Get catalogs</Press>}
        />
        <Setting
          label="Connect your browser"
          note={
            extension?.connected
              ? 'The extension is connected to this app.'
              : extension?.ever_connected
                ? 'It was connected before. Open a product page to check the connection again.'
                : 'Add Kriko to Chrome, then open any product page. The connection shows here.'
          }
          state={<State tone={browserDone ? 'ok' : undefined}>{browserDone ? 'Done' : 'To do'}</State>}
          control={
            <>
              <Press tone="quiet" onClick={() => void reload()}>Check browser connection</Press>
              <ExternalLink className="k-btn" data-kind={next === 2 ? 'primary' : 'quiet'} href={STORE}>
                Add Kriko to Chrome
              </ExternalLink>
            </>
          }
        />
        <Setting
          label="Run a first sourced check"
          note="In Chat, name a product and ask for known problems with sources. A connection test alone does not check source access."
          state={<State>To do</State>}
          control={<Press tone={primary(3)} onClick={() => showDrawer(null)}>Start a sourced check</Press>}
        />
        <details className="settings-fold">
          <summary>Have an access code from a friend?</summary>
          <div className="settings-fold-body">
            <p className="settings-note">Paste the code and password under Keys and models. You do not need your own API keys or another agent installed.</p>
            <Press tone="quiet" onClick={() => showSettingsPage('keys')}>Open Keys and models</Press>
          </div>
        </details>
        <details className="settings-fold">
          <summary>Installing from a checkout instead</summary>
          <div className="settings-fold-body">
            <p className="settings-note">For a development build. Open your browser's Extensions page, enable Developer mode, choose Load unpacked, and select this folder.</p>
            <div className="settings-actions-row">
              <Press tone="quiet" disabled={working || mode !== 'live'} onClick={() => void stage()}>Prepare extension folder</Press>
              {extension?.staged && (
                <Press
                  tone="quiet"
                  onClick={() => void post('/api/extension/reveal', {}).catch((error: unknown) => setStatus(error instanceof Error ? error.message : 'Could not open the folder.'))}
                >
                  Open extension folder
                </Press>
              )}
            </div>
            {extension?.staged && <p className="settings-path">{extension.path}</p>}
          </div>
        </details>
      </Section>
      {status && (
        <p role="status" className="settings-status">
          {status}
        </p>
      )}
    </>
  )
}
