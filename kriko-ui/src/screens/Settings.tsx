import { useEffect, useRef, useState, type ComponentType } from 'react'
import { Icon, type IconName } from '../ui/Icon'
import { SETTINGS_PAGES, isSettingsPage, onSettingsPage, takeRequestedSettingsPage, type SettingsPage } from '../ui/panels/settingsPages'
import { Connections } from '../ui/settings/Connections'
import { Data } from '../ui/settings/Data'
import { General } from '../ui/settings/General'
import { Keys } from '../ui/settings/Keys'
import { LocalAI } from '../ui/settings/LocalAI'
import { Research } from '../ui/settings/Research'
import { Usage } from '../ui/settings/Usage'

/** Settings: a list of seven sections on the left, the open one on the right. The
 *  search field finds a setting by its name or its note in any section. */

const ICONS: Record<SettingsPage, IconName> = {
  general: 'palette',
  research: 'search',
  keys: 'key',
  local: 'cpu',
  connections: 'plug',
  usage: 'chart',
  data: 'folder',
}

const PANES: Record<SettingsPage, ComponentType> = {
  general: General,
  research: Research,
  keys: Keys,
  local: LocalAI,
  connections: Connections,
  usage: Usage,
  data: Data,
}

interface Match {
  page: SettingsPage
  label: string
  note: string
}

function sameMatches(a: Match[], b: Match[]): boolean {
  return a.length === b.length && a.every((one, i) => one.page === b[i].page && one.label === b[i].label && one.note === b[i].note)
}

export function SettingsScreen({ initial }: { initial?: string | null }) {
  const [page, setPage] = useState<SettingsPage>(isSettingsPage(initial) ? initial : 'general')
  const [query, setQuery] = useState('')
  const [matches, setMatches] = useState<Match[]>([])
  const indexRef = useRef<HTMLDivElement>(null)
  const needle = query.trim().toLowerCase()
  const searching = needle.length > 0

  // A section the tour asked for before this screen mounted, then one asked while open.
  useEffect(() => {
    const requested = takeRequestedSettingsPage()
    if (requested) setPage(requested)
    return onSettingsPage(setPage)
  }, [])

  // A new `initial` from the shell moves the screen; the same one does not.
  const [seenInitial, setSeenInitial] = useState(initial)
  if (initial !== seenInitial) {
    setSeenInitial(initial)
    if (isSettingsPage(initial)) setPage(initial)
  }

  // While searching, every section is drawn once, hidden, and its rows are read
  // back from the page. A row is a `[data-setting]` with its label and note.
  useEffect(() => {
    const root = indexRef.current
    if (!searching || !root) return
    const scan = () => {
      const found: Match[] = []
      root.querySelectorAll<HTMLElement>('[data-setting]').forEach((row) => {
        const label = row.querySelector('[data-setting-label]')?.textContent?.trim() ?? ''
        const section = row.closest<HTMLElement>('[data-section]')?.dataset.section
        if (!label || !isSettingsPage(section)) return
        const note = row.querySelector('.k-row-note')?.textContent?.trim() ?? ''
        if (`${label} ${note}`.toLowerCase().includes(needle)) found.push({ page: section, label, note })
      })
      setMatches((previous) => (sameMatches(previous, found) ? previous : found))
    }
    scan()
    const observer = new MutationObserver(scan)
    observer.observe(root, { childList: true, subtree: true, characterData: true })
    return () => observer.disconnect()
  }, [searching, needle])

  // Nothing is shown from an old search once the query is cleared.
  const found = searching ? matches : []

  const choose = (next: SettingsPage) => {
    setPage(next)
    setQuery('')
  }

  const Pane = PANES[page]
  const label = SETTINGS_PAGES.find((one) => one.value === page)?.label ?? ''

  return (
    <div className="k-screen settings-screen" data-width="wide">
      <div className="k-head">
        <h1 className="k-title">Settings</h1>
        <div className="k-head-actions">
          <input
            type="search"
            className="k-input settings-search"
            aria-label="Search settings"
            placeholder="Search settings"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Escape') setQuery('')
            }}
          />
        </div>
      </div>

      <div className="settings-body">
        <nav className="settings-nav" aria-label="Settings sections">
          <div className="k-card k-list">
            {SETTINGS_PAGES.map((one) => (
              <button key={one.value} type="button" className="k-row" aria-current={!searching && one.value === page ? 'true' : undefined} onClick={() => choose(one.value)}>
                <span className="k-row-icon" aria-hidden="true">
                  <Icon name={ICONS[one.value]} size={18} />
                </span>
                <span className="k-row-title">{one.label}</span>
              </button>
            ))}
          </div>
        </nav>

        <div className="settings-main">
          <select className="k-input settings-jump" aria-label="Settings section" value={page} onChange={(event) => choose(event.target.value as SettingsPage)}>
            {SETTINGS_PAGES.map((one) => (
              <option key={one.value} value={one.value}>
                {one.label}
              </option>
            ))}
          </select>

          {searching ? (
            <div className="settings-results">
              {found.length === 0 ? (
                <div className="k-empty">
                  <strong>No setting matches "{query.trim()}"</strong>
                  <span>Try a word from its name or from its note.</span>
                </div>
              ) : (
                SETTINGS_PAGES.filter((one) => found.some((match) => match.page === one.value)).map((one) => (
                  <section key={one.value} className="k-group settings-section">
                    <h2 className="k-caption">{one.label}</h2>
                    <div className="k-card k-list">
                      {found
                        .filter((match) => match.page === one.value)
                        .map((match, index) => (
                          <button key={index} type="button" className="k-row" onClick={() => choose(one.value)}>
                            <span className="k-row-main">
                              <span className="k-row-title">{match.label}</span>
                              {match.note && <span className="k-row-note">{match.note}</span>}
                            </span>
                            <span className="k-row-chevron" aria-hidden="true">
                              <Icon name="chevron" size={16} />
                            </span>
                          </button>
                        ))}
                    </div>
                  </section>
                ))
              )}
            </div>
          ) : (
            <section className="settings-pane" key={page}>
              <h2 className="settings-pane-title">{label}</h2>
              <Pane />
            </section>
          )}
        </div>
      </div>

      {searching && (
        <div ref={indexRef} hidden>
          {SETTINGS_PAGES.map((one) => {
            const Section = PANES[one.value]
            return (
              <div key={one.value} data-section={one.value}>
                <Section />
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
