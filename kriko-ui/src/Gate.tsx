import App from './App'
import { UpdateProvider } from './engine/appupdate'
import { useEngine } from './engine/Engine'
import { Starting } from './ui/Starting'
import { UpdateNotice } from './ui/UpdateNotice'

/** Nothing that reads the engine is drawn until it has answered or been given up on. */
export function Gate() {
  const { mode, problem, retry } = useEngine()
  if (mode === 'checking') return <Starting />
  if (mode === 'offline') return (
    <div className="starting" role="alert">
      <h1>Kriko could not connect</h1>
      <p>{problem || 'The engine is unavailable. Your saved work stays on this computer.'}</p>
      <button className="btn primary" onClick={retry}>Reconnect</button>
      <button className="btn" onClick={() => { window.location.search = '?demo' }}>Explore demo data</button>
    </div>
  )
  return (
    <UpdateProvider>
      {mode === 'demo' && <aside className="demo-banner" role="status">Demo — example answers. No research is running. <button onClick={() => { window.location.search = '' }}>Connect to Kriko</button></aside>}
      <App />
      <UpdateNotice />
    </UpdateProvider>
  )
}
