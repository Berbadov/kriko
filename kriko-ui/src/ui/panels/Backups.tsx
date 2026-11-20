import { useState } from 'react'
import { post, uploadArtifact, inShell } from '../../engine/api'
import { useEngine } from '../../engine/Engine'
import { FileUpload } from '../../arc/file-upload/file-upload'
import type { FileUploadItem } from '../../arc/file-upload/file-upload'

/** Back up now, and restore from a file with a confirm step in words. Drawn inside
 *  Settings, Data and updates, once the reader opens it. */
export function BackupsPanel() {
  const { mode, retry } = useEngine()
  const [file, setFile] = useState<File | null>(null)
  const [working, setWorking] = useState(false)
  const [staged, setStaged] = useState(false)
  const [status, setStatus] = useState('')
  const [picked, setPicked] = useState<FileUploadItem[]>([])

  const save = async () => {
    setWorking(true)
    try {
      const saved = await post<{ filename: string; data: string }>('/api/backups/export', {}, 60000)
      const bytes = Uint8Array.from(atob(saved.data), (ch) => ch.charCodeAt(0))
      const url = URL.createObjectURL(new Blob([bytes], { type: 'application/zip' }))
      const link = document.createElement('a')
      link.href = url
      link.download = saved.filename
      link.click()
      window.setTimeout(() => URL.revokeObjectURL(url), 30000)
      setStatus('Snapshot prepared. Keep the ZIP in a safe location.')
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'The snapshot could not be created.')
    } finally {
      setWorking(false)
    }
  }

  const restore = async () => {
    if (!file) return
    setWorking(true)
    try {
      await uploadArtifact('/api/backups/restore', file)
      setStaged(true)
      setStatus('Snapshot validated and staged. Restart Kriko to restore it.')
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'The snapshot could not be restored.')
    } finally {
      setWorking(false)
    }
  }

  return (
    <div className="settings-data-panel-body">
      <div className="settings-data-block">
        <h4>Back up now</h4>
        <p className="settings-data-words">
          Includes saved checks, conversations, settings, catalog revisions and data-only drafts. Provider key files are excluded. Stop active research first.
        </p>
        <div>
          <button type="button" className="k-btn" data-kind="primary" onClick={() => void save()} disabled={working || mode !== 'live'}>
            Back up now
          </button>
        </div>
      </div>

      <div className="settings-data-block">
        <h4>Restore from a file</h4>
        <FileUpload
          accept=".zip"
          multiple={false}
          disabled={working}
          label="Choose a snapshot"
          description="Drop a snapshot ZIP here, or browse for one."
          value={picked}
          onChange={(items) => {
            setPicked(items)
            setFile(items.find((item) => !item.error)?.file ?? null)
            setStaged(false)
          }}
        />
        {file && !staged && (
          <div className="settings-data-confirm" role="group" aria-label="Confirm the restore">
            <p className="settings-data-words">
              Restore <strong>{file.name}</strong>? On restart, this replaces the current saved work and settings with the snapshot. Kriko keeps the previous databases beside
              the restored files. Provider keys stay unchanged.
            </p>
            <div className="settings-data-controls">
              <button type="button" className="k-btn" disabled={working || mode !== 'live'} onClick={() => void restore()}>
                Restore this snapshot after restart
              </button>
              <button
                type="button"
                className="k-btn"
                data-kind="quiet"
                onClick={() => {
                  setFile(null)
                  setPicked([])
                }}
              >
                Keep current data
              </button>
            </div>
          </div>
        )}
        {staged &&
          (inShell() ? (
            <div>
              <button type="button" className="k-btn" data-kind="primary" onClick={retry}>
                Restart and restore
              </button>
            </div>
          ) : (
            <p className="settings-data-words">Stop the local engine and start it again to apply the restore.</p>
          ))}
      </div>

      {status && (
        <p role="status" className="settings-data-status">
          {status}
        </p>
      )}
    </div>
  )
}
