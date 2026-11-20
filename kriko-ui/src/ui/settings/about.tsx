import { useAppUpdate } from '../../engine/appupdate'
import { useAbout, usePresence, usePrefsDoc } from '../../engine/settings'
import { Section, Setting, State, Toggle } from '../panels/settingsParts'

/** Version and updates, and what this copy sends. The product-lookup switch is
 *  not drawn here: it lives in Keys and models, and this section only names it. */

/** Opens a release page in the reader's browser. Loaded when it is pressed, so the page itself reads no engine code. */
const openPage = async (href: string) => (await import('../ExternalLink')).openLink(href)

const isMac = () => typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || '')

/** The one state a row shows beside its name. */
function updatePill(phase: string, release: unknown, checked: boolean) {
  if (phase === 'checking') return <State>Checking</State>
  if (phase === 'downloading') return <State>Downloading</State>
  if (phase === 'installing') return <State>Installing</State>
  if (phase === 'restarting') return <State>Starting</State>
  if (release) return <State tone="ok">Update available</State>
  if (checked) return <State>Up to date</State>
  return undefined
}

function updateNote(release: { engine: boolean } | null, canInstall: boolean): string {
  if (release?.engine) return 'The engine restarts and the window stays open. A run in progress stops. Your chats and catalogs stay.'
  if (release && canInstall) return 'Kriko closes, updates and opens again. Your chats and catalogs stay.'
  if (release) return 'Download the new version from its release page and install it by hand.'
  return 'Kriko looks for a new version a few seconds after it starts, and every six hours while it is open.'
}

/** The app version, whether a newer release exists, the two update buttons the
 *  code allows, and the weekly catalog check. */
export function UpdatesSection() {
  const update = useAppUpdate()
  const about = useAbout()
  const { release, phase, problem, checked, canInstall } = update
  const busy = phase !== 'idle'
  const installable = !!release && (canInstall || release.engine)

  return (
    <Section title="Version and updates">
      <Setting icon="cpu" label="Version" value={about?.version || 'Not known'} note="The version of Kriko running on this computer." />
      <Setting
        icon="download"
        label="Updates"
        state={updatePill(phase, release, checked)}
        value={release ? `Version ${release.version}` : undefined}
        note={updateNote(release, canInstall)}
        control={
          <span className="settings-data-controls">
            {release && installable && (
              <button type="button" className="k-btn" data-kind="primary" disabled={busy} onClick={() => void update.install()}>
                Install update
              </button>
            )}
            {release && !installable && (
              <button type="button" className="k-btn" data-kind="primary" disabled={!release.page} onClick={() => void openPage(release.page)}>
                Open the download page
              </button>
            )}
            <button type="button" className="k-btn" disabled={busy} onClick={() => void update.check()}>
              {phase === 'checking' ? 'Checking…' : 'Check now'}
            </button>
          </span>
        }
      />
      {problem && phase === 'idle' && (
        <p className="error-note settings-data-problem" role="alert">
          {problem}
        </p>
      )}
      <Setting
        icon="shield"
        label="How this copy updates"
        value={canInstall ? 'Installer' : isMac() ? 'Disk image' : 'By hand'}
        note={
          canInstall
            ? 'Install update closes Kriko and runs the Windows installer, which puts the new version in place.'
            : isMac()
              ? 'The Mac app does not update itself. Download the next disk image from the release page.'
              : 'This copy was not set up by the installer, so a new version is downloaded by hand.'
        }
      />
      <Setting
        icon="book"
        label="Catalog updates"
        value="Weekly"
        note="Installed catalogs are checked at start-up when the last good check is over a week old. The time of that check is not shown here yet."
      />
    </Section>
  )
}

/** The daily ping, what it holds, and the product-lookup state, with its words. */
export function SendsSection() {
  const { doc, save } = usePrefsDoc()
  const { presence, reload: reloadPresence } = usePresence()
  const pingOn = doc?.chosen.presence_enabled === '1' || !!presence?.enabled
  const shared = doc?.chosen.share_queries === '1'

  return (
    <Section
      title="What this copy sends"
      note={
        <>
          Product lookups are shared only when you turn that on in Keys and models, under Share which products are looked up. Then Kriko sends the product model you
          looked up (for example "Brand Model 128GB") and whether our catalog had it. It never sends the listing link, the page title, the time, or anything that identifies
          you or your device. Off by default. Read the <a href="https://kriko.cc/privacy/">privacy policy</a>.
        </>
      }
    >
      {presence && (
        <Setting
          icon="bell"
          label="Daily ping"
          note={
            <>
              Once a day: a random install id and the app version, nothing else. Read the <a href="https://kriko.cc/privacy/">privacy policy</a>.
              {!presence.endpoint && ' No endpoint is set, so nothing leaves this computer.'}
            </>
          }
          control={
            <Toggle
              label="Anonymous daily ping"
              on={pingOn}
              onChange={(on) => void save({ presence_enabled: on ? '1' : '0' }).then(() => void reloadPresence())}
            />
          }
        />
      )}
      {presence && pingOn && <Setting icon="clock" label="Last ping sent" value={presence.last_day || 'On the next start'} note="The day the last ping was sent." />}
      {doc && (
        <Setting
          icon="search"
          label="Product lookups"
          value={shared ? 'Shared' : 'Not shared'}
          note="Only the product model you looked up, and whether our catalog had it."
        />
      )}
      <Setting
        icon="download"
        label="Update checks"
        note="Looking for a new version of Kriko, and for catalog updates, is a request to where they are published."
      />
    </Section>
  )
}
