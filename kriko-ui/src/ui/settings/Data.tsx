import { lazy, Suspense, useState, type ReactNode } from 'react'
import { useAbout } from '../../engine/settings'
import { hasRequestedReport } from '../../engine/reportformat'
import { Setting } from '../panels/settingsParts'
import { SendsSection, UpdatesSection } from './about'

/** The three panels that read the engine load when the reader opens them. */
const BackupsPanel = lazy(() => import('../panels/Backups').then((one) => ({ default: one.BackupsPanel })))
const LogsPanel = lazy(() => import('../panels/Logs').then((one) => ({ default: one.LogsPanel })))
const ReportPanel = lazy(() => import('../panels/Report').then((one) => ({ default: one.ReportPanel })))

const Opening = () => <p className="settings-data-words">Opening…</p>

/** Data and updates: the version and its updates, backup and restore, what this
 *  copy sends, the log, and the report. The panels that read the engine are
 *  drawn only when the reader opens them, so the page itself never waits on one. */
export function Data() {
  return (
    <>
      <UpdatesSection />
      <BackupSection />
      <SendsSection />
      <LogSection />
      <ReportSection />
    </>
  )
}

/** A section whose rows are followed by one block that opens under them. */
function ExpandSection({ title, children, below }: { title: string; children: ReactNode; below?: ReactNode }) {
  return (
    <section className="k-group settings-section">
      <div className="settings-section-head">
        <h3 className="k-caption">{title}</h3>
      </div>
      <div className="k-card k-list">{children}</div>
      {below}
    </section>
  )
}

function BackupSection() {
  const about = useAbout()
  const [open, setOpen] = useState(false)
  return (
    <ExpandSection
      title="Back up and restore"
      below={
        open && (
          <div className="k-card settings-data-panel">
            <Suspense fallback={<Opening />}>
              <BackupsPanel />
            </Suspense>
          </div>
        )
      }
    >
      <Setting icon="folder" label="Your data" value={<span className="settings-data-path">{about?.folder || 'Not known'}</span>} note="Your chats, settings and catalogs are kept in this folder." />
      <Setting
        icon="download"
        label="Your backups"
        note="Save one ZIP file of your work and settings, or put a saved one back from a file."
        control={
          <button type="button" className="k-btn" aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? 'Hide backups' : 'Back up or restore'}
          </button>
        }
      />
    </ExpandSection>
  )
}

function LogSection() {
  const [open, setOpen] = useState(false)
  return (
    <ExpandSection
      title="Logs"
      below={
        open && (
          <div className="settings-data-scroll">
            <Suspense fallback={<Opening />}>
              <LogsPanel />
            </Suspense>
          </div>
        )
      }
    >
      <Setting
        icon="clock"
        label="Job log"
        note="Every step of every job, with its time. Filter it, or open a step for its exact request and reply."
        control={
          <button type="button" className="k-btn" aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? 'Hide the log' : 'Show the log'}
          </button>
        }
      />
    </ExpandSection>
  )
}

function ReportSection() {
  // A problem reported from elsewhere opens this form on its run.
  const [open, setOpen] = useState(() => hasRequestedReport())
  return (
    <ExpandSection
      title="Report a problem or suggest"
      below={
        open && (
          <div className="k-card settings-data-panel">
            <Suspense fallback={<Opening />}>
              <ReportPanel />
            </Suspense>
          </div>
        )
      }
    >
      <Setting
        icon="alert"
        label="Write a report"
        note="Kriko writes the report and shows all of it. Nothing is sent until you press Submit on GitHub."
        control={
          <button type="button" className="k-btn" aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? 'Close the form' : 'Write a report'}
          </button>
        }
      />
    </ExpandSection>
  )
}
