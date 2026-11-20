import { providerState, useSearchProviders, type SearchHealth, type SearchProviderRow, type SearchTest } from '../../engine/websearch'
import { Section, SelectField, Setting, State } from './settingsParts'
import { showSettingsPage } from './settingsPages'

/** "3 min ago", from seconds since the epoch. */
function ago(seconds: number | null): string {
  if (!seconds) return ''
  const gap = Math.max(0, Math.round(Date.now() / 1000) - seconds)
  if (gap < 90) return 'just now'
  if (gap < 3600) return `${Math.round(gap / 60)} min ago`
  if (gap < 86400) return `${Math.round(gap / 3600)} h ago`
  return `${Math.round(gap / 86400)} days ago`
}

/** What the reader needs to judge a provider: when it last answered and how often it has not. */
function healthLine(health: SearchHealth): string {
  const parts: string[] = []
  parts.push(health.last_success ? `Last answered ${ago(health.last_success)}` : 'Has not answered yet')
  if (health.miss_rate !== null && health.recent) {
    const misses = Math.round(health.miss_rate * health.recent)
    parts.push(misses === 0 ? `all of the last ${health.recent} searches gave results` : `${misses} of the last ${health.recent} searches gave nothing`)
  }
  return `${parts.join(' · ')}.`
}

/** A trouble is shown while it is the latest word: a failure newer than the last answer. */
function troubleLine(health: SearchHealth): string {
  if (!health.last_failure || !health.last_problem) return ''
  if (health.last_success && health.last_success > health.last_failure) return ''
  return `Trouble ${ago(health.last_failure)}: ${health.last_problem}`
}

/** The order words the rows carry, from the first one asked. */
const ORDER = ['First', 'Second', 'Third', 'Fourth', 'Fifth', 'Sixth']

/** Which service searches the web, what it falls back to, and whether each one works.
 *  The first provider and the order are set here; each provider is one row. */
export function SearchProvidersGroup() {
  const { doc, problem, tested, save, test, reload } = useSearchProviders()
  if (!doc)
    return problem ? (
      <p className="error-note" role="alert">
        Could not read search providers. {problem}{' '}
        <button type="button" className="k-btn" data-size="sm" onClick={() => void reload()}>
          Try again
        </button>
      </p>
    ) : null

  const write = (list: string[]) => void save({ search_fallback: list.length ? list.join(',') : 'none' })
  const move = (index: number, by: number) => {
    const next = [...doc.fallback]
    const [one] = next.splice(index, 1)
    next.splice(index + by, 0, one)
    write(next)
  }

  return (
    <Section
      title="Web search"
      tour="web-search"
      note="Kriko asks the first provider. When it fails or finds nothing, it asks the next one in order. A hosted provider receives the words you search."
    >
      {problem && <p className="error-note">{problem}</p>}

      <Setting
        label="First provider"
        note="Kriko asks this one first for every search."
        control={
          <SelectField
            label="First search provider"
            value={doc.primary}
            options={doc.providers.map((row) => ({ value: row.id, label: row.needs_key && !row.key_saved ? `${row.label} (no key)` : row.label }))}
            onChange={(value) => void save({ search_provider: value })}
          />
        }
      />

      <Setting
        label="Then"
        note={doc.automatic ? 'Automatic: Kriko chooses the order of the others from the providers that are ready.' : 'Kriko asks these in the order shown, after the first.'}
        state={doc.automatic ? <State>Automatic</State> : undefined}
        control={
          !doc.automatic ? (
            <button type="button" className="k-btn" data-kind="quiet" onClick={() => void save({ search_fallback: '' })}>
              Automatic order
            </button>
          ) : undefined
        }
      />

      {doc.providers.map((row) => {
        const index = doc.fallback.indexOf(row.id)
        const inOrder = !doc.automatic && index >= 0
        const position = row.id === doc.primary ? ORDER[0] : inOrder ? (ORDER[index + 1] ?? `Number ${index + 2}`) : undefined
        return (
          <ProviderRow
            key={row.id}
            row={row}
            effective={doc.effective}
            position={position}
            order={inOrder ? { index, last: doc.fallback.length - 1 } : undefined}
            canAdd={row.id !== doc.primary && !inOrder}
            onAdd={() => write([...doc.fallback, row.id])}
            onMove={(by) => move(index, by)}
            onRemove={() => write(doc.fallback.filter((one) => one !== row.id))}
            onTest={() => void test(row.id)}
            result={tested[row.id]}
          />
        )
      })}
    </Section>
  )
}

/** One provider: its state in a pill, its engine note, its place in the order, and
 *  the presses. The last answer or the trouble sits under the row, in words. */
function ProviderRow({
  row,
  effective,
  position,
  order,
  canAdd,
  onAdd,
  onMove,
  onRemove,
  onTest,
  result,
}: {
  row: SearchProviderRow
  effective: string[]
  position?: string
  order?: { index: number; last: number }
  canAdd: boolean
  onAdd: () => void
  onMove: (by: number) => void
  onRemove: () => void
  onTest: () => void
  result: SearchTest | 'testing' | undefined
}) {
  const state = providerState(row, effective)
  const trouble = troubleLine(row.health)
  const testing = result === 'testing'
  const sub = row.health.calls > 0 ? healthLine(row.health) : ''
  const keyMissing = row.needs_key && !row.key_saved
  return (
    <div className="settings-item">
      <Setting
        label={row.label}
        value={position}
        state={<State tone={state.tone}>{state.text}</State>}
        note={
          <>
            {row.note}
            {sub && <span className="settings-sub">{sub}</span>}
          </>
        }
        control={
          <>
            {order && (
              <>
                <button type="button" className="k-btn" data-size="sm" data-kind="quiet" aria-label={`Move ${row.label} earlier`} disabled={order.index === 0} onClick={() => onMove(-1)}>
                  Earlier
                </button>
                <button type="button" className="k-btn" data-size="sm" data-kind="quiet" aria-label={`Move ${row.label} later`} disabled={order.index === order.last} onClick={() => onMove(1)}>
                  Later
                </button>
                <button type="button" className="k-btn" data-size="sm" data-kind="danger" aria-label={`Stop asking ${row.label}`} onClick={onRemove}>
                  Remove
                </button>
              </>
            )}
            {canAdd && (
              <button type="button" className="k-btn" data-size="sm" data-kind="quiet" onClick={onAdd}>
                Add to the order
              </button>
            )}
            {keyMissing && (
              <button type="button" className="k-btn" data-size="sm" data-kind="quiet" onClick={() => showSettingsPage('keys')}>
                Add a key
              </button>
            )}
            <button type="button" className="k-btn" data-size="sm" aria-label={testing ? `Testing ${row.label}` : `Test ${row.label}`} disabled={testing} onClick={onTest}>
              {testing ? 'Testing…' : 'Test'}
            </button>
          </>
        }
      />
      {trouble && <p className="settings-trouble">{trouble}</p>}
      {result && result !== 'testing' && <TestResult result={result} />}
    </div>
  )
}

/** The outcome of a test: the answer and its results, or the words why not. */
function TestResult({ result }: { result: SearchTest }) {
  if (!result.ok) return <p className="settings-test" data-ok="false">{result.error || 'It did not answer.'}</p>
  return (
    <div className="settings-test" data-ok="true">
      <p>
        Answered in {(result.ms / 1000).toFixed(1)} s with {result.results.length} {result.results.length === 1 ? 'result' : 'results'} for “{result.query}”.
      </p>
      <ul>
        {result.results.map((hit) => (
          <li key={hit.url}>
            <span>{hit.title || hit.url}</span>
            <small>{hit.site}</small>
          </li>
        ))}
      </ul>
    </div>
  )
}
