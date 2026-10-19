import { useRef, useState } from 'react'
import { post, uploadArtifact, inShell } from '../../engine/api'
import { useEngine } from '../../engine/Engine'

export function BackupsPanel() {
  const { mode, retry } = useEngine()
  const [file, setFile] = useState<File | null>(null)
  const [working, setWorking] = useState(false)
  const [staged, setStaged] = useState(false)
  const [status, setStatus] = useState('')
  const input = useRef<HTMLInputElement>(null)
  const save = async () => {
    setWorking(true)
    try {
      const saved = await post<{filename: string; data: string}>('/api/backups/export', {}, 60000)
      const bytes = Uint8Array.from(atob(saved.data), (ch) => ch.charCodeAt(0))
      const url = URL.createObjectURL(new Blob([bytes], {type: 'application/zip'}))
      const link = document.createElement('a'); link.href = url; link.download = saved.filename; link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 30000)
      setStatus('Snapshot prepared. Keep the ZIP in a safe location.')
    } catch (error) { setStatus(error instanceof Error ? error.message : 'The snapshot could not be created.') }
    finally { setWorking(false) }
  }
  const restore = async () => {
    if (!file) return
    setWorking(true)
    try { await uploadArtifact('/api/backups/restore', file); setStaged(true); setStatus('Snapshot validated and staged. Restart Kriko to restore it.') }
    catch (error) { setStatus(error instanceof Error ? error.message : 'The snapshot could not be restored.') }
    finally { setWorking(false) }
  }
  return <div className="panel-body">
    <section className="panel-group"><h3>Save a snapshot</h3><p>Includes saved checks, conversations, settings, catalog revisions and data-only drafts. Provider key files are excluded. Stop active research first.</p><button className="btn" onClick={() => void save()} disabled={working || mode !== 'live'}>Export snapshot</button></section>
    <section className="panel-group"><h3>Restore a snapshot</h3>
      <input ref={input} type="file" accept=".zip" onChange={(event) => { setFile(event.target.files?.[0] ?? null); setStaged(false) }} />
      {file && !staged && <><p>Restore <strong>{file.name}</strong>? On restart, this replaces the current saved work and settings with the snapshot. Kriko keeps the previous databases beside the restored files. Provider keys stay unchanged.</p><button className="btn" disabled={working || mode !== 'live'} onClick={() => void restore()}>Restore this snapshot after restart</button><button className="btn ghost" onClick={() => { setFile(null); if (input.current) input.current.value = '' }}>Keep current data</button></>}
      {staged && (inShell() ? <button className="btn primary" onClick={retry}>Restart and restore</button> : <p>Stop the local engine and start it again to apply the restore.</p>)}
    </section>
    {status && <p role="status">{status}</p>}
  </div>
}
