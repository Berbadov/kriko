import { useAppUpdate } from '../engine/appupdate'
import { openLink } from './ExternalLink'

/** A new version, offered once and never pushed. It sits over the corner of the
 *  window until the reader updates or says later. */
export function UpdateNotice() {
  const { release, phase, problem, canInstall, dismissed, install, dismiss } = useAppUpdate()
  if (!release || (dismissed && phase === 'idle' && !problem)) return null
  const working = phase === 'downloading' || phase === 'installing'
  return (
    <aside className="update-notice" role="status" aria-live="polite">
      <strong>Kriko {release.version} is ready</strong>
      <p>
        {phase === 'downloading'
          ? 'Downloading the update…'
          : phase === 'installing'
            ? 'Installing. Kriko closes and opens again by itself.'
            : canInstall
              ? 'Kriko closes, updates and opens again. Your chats and catalogs stay.'
              : 'This copy was not set up by the installer, so the new version is downloaded by hand.'}
      </p>
      {problem && <p className="error-note">{problem}</p>}
      {working ? (
        <span className="starting-bar" aria-hidden="true" />
      ) : (
        <div className="update-actions">
          {canInstall ? (
            <button className="btn primary" onClick={() => void install()}>
              Update now
            </button>
          ) : (
            <button className="btn primary" onClick={() => void openLink(release.page)} disabled={!release.page}>
              Open the download page
            </button>
          )}
          <button className="btn ghost" onClick={dismiss}>
            Later
          </button>
        </div>
      )}
    </aside>
  )
}
