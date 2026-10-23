import { useEffect, useState } from 'react'
import { get, post } from '../../engine/api'
import { followJob } from '../../engine/jobs'
import { useEngine } from '../../engine/Engine'
import { showDrawer } from '../drawerEvents'
import { ExternalLink } from '../ExternalLink'
import { SharedAccessGroup } from './Settings'

type Extension = { connected: boolean; staged: boolean; path: string; ever_connected: boolean }

/** The published listing. A reader installs from here; a checkout still has the folder. */
const STORE = 'https://chromewebstore.google.com/detail/kriko/bdifnaggafjokndlpjgmlfappcoehdjb'

export function SetupPanel() {
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
  return <div className="panel-body">
    <section className="panel-group"><h3>1. Choose who does the research</h3>
      <details className="setup-dev">
        <summary>Have an access code from a friend?</summary>
        <p className="panel-note">Paste the code and password below. You do not need your own API keys or another agent installed.</p>
        <SharedAccessGroup />
      </details>
      <p>{verified ? 'Connection verified for this check.' : 'An installed agent still needs a working account and model connection.'}</p>
      <button className="btn" onClick={() => showDrawer('agents')}>Choose agent</button>{' '}
      <button className="btn" onClick={() => void verify()} disabled={working || mode !== 'live'}>Check connection</button>
      <p className="panel-note">This sends a short request using your selected provider.</p>
    </section>
    <section className="panel-group"><h3>2. Add product knowledge</h3>
      <p>{catalogs === null ? 'Check which catalogs are installed.' : `${catalogs} catalogs installed. Research can also read public sources for a new product.`}</p>
      <button className="btn" onClick={() => showDrawer('browse')}>Get catalogs</button>
    </section>
    <section className="panel-group"><h3>3. Connect your browser</h3>
      <p>{extension?.connected ? 'The extension is connected.' : extension?.ever_connected ? 'Connected before; open a product page to check the connection again.' : 'Add Kriko to Chrome, then open any product page. The connection shows up here.'}</p>
      <ExternalLink className="btn primary" href={STORE}>Add Kriko to Chrome</ExternalLink>{' '}
      <button className="btn" onClick={() => void reload()}>Check browser connection</button>
      <details className="setup-dev">
        <summary>Installing from a checkout instead</summary>
        <p className="panel-note">For a development build. Open your browser's Extensions page, enable Developer mode, choose Load unpacked, and select this folder.</p>
        <button className="btn" onClick={() => void stage()} disabled={working || mode !== 'live'}>Prepare extension folder</button>
        {extension?.staged && <><p className="panel-path">{extension.path}</p><button className="btn" onClick={() => void post('/api/extension/reveal', {}).catch((error: unknown) => setStatus(error instanceof Error ? error.message : 'Could not open the folder.'))}>Open extension folder</button></>}
      </details>
    </section>
    <section className="panel-group"><h3>4. Complete your first check</h3><p>In Chat, name a product and ask for known problems with sources. Open a source, ask a follow-up, then add the product to Compare. A connection test alone does not verify source access.</p><button className="btn" onClick={() => showDrawer(null)}>Start a sourced check</button></section>
    {status && <p role="status">{status}</p>}
  </div>
}
