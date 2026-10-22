import { useSearchProviders, type SearchHealth, type SearchProviderRow, type SearchTest } from '../../engine/websearch'
import { Select } from '../controls'
import '../../styles/providers.css'

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
  if (!health.calls) return 'Not used yet.'
  const parts: string[] = []
  parts.push(health.last_success ? `Last answered ${ago(health.last_success)}` : 'Has not answered yet')
  if (health.miss_rate !== null && health.recent) {
    const misses = Math.round(health.miss_rate * health.recent)
    parts.push(misses === 0 ? `all of the last ${health.recent} searches gave results` : `${misses} of the last ${health.recent} searches gave nothing`)
  }
  if (health.last_failure && health.last_problem) parts.push(`last trouble ${ago(health.last_failure)}: ${health.last_problem}`)
  return `${parts.join(' · ')}.`
}

function keyLine(row: SearchProviderRow): string {
  if (!row.needs_key) return 'No key needed.'
  return row.key_saved ? 'Key saved.' : 'Needs a key. Add it under Keys below.'
}

/** Which service searches the web, what it falls back to, and whether each one works. */
export function SearchProvidersGroup() {
  const { doc, problem, tested, save, test, reload } = useSearchProviders()
  if (!doc) return problem ? <p className="error-note" role="alert">Could not read search providers. {problem} <button className="btn" onClick={() => void reload()}>Try again</button></p> : null
  const byId = new Map(doc.providers.map((row) => [row.id, row]))
  const label = (id: string) => byId.get(id)?.label ?? id
  const addable = doc.providers.filter((row) => row.id !== doc.primary && !doc.fallback.includes(row.id))
  const write = (list: string[]) => void save({ search_fallback: list.length ? list.join(',') : 'none' })
  const move = (index: number, by: number) => {
    const next = [...doc.fallback]
    const [one] = next.splice(index, 1)
    next.splice(index + by, 0, one)
    write(next)
  }

  return (
    <section className="panel-group" data-tour="web-search">
      <h3>Web search</h3>
      <p className="panel-note">Chat and research search the web with the first choice. If it fails or finds nothing, the next one is asked, and the job log says so.</p>
      {problem && <p className="error-note">{problem}</p>}

      <div className="setting">
        <span>
          First choice
          <small>{doc.primary === 'openserp' ? 'Runs on this computer. The default.' : `${label(doc.primary)} is asked first.`}</small>
        </span>
        <Select
          label="First search provider"
          value={doc.primary}
          options={doc.providers.map((row) => ({ value: row.id, label: row.needs_key && !row.key_saved ? `${row.label} (no key)` : row.label }))}
          onChange={(value) => void save({ search_provider: value === 'openserp' ? '' : value })}
        />
      </div>

      <div className="setting stack">
        <span>
          If that fails or finds nothing
          <small>
            {doc.automatic
              ? 'Automatic: DeepSeek is asked next once it has a key. No other provider is asked unless you add it.'
              : doc.fallback.length
                ? 'Asked in this order.'
                : 'Nothing is asked after the first choice.'}
          </small>
        </span>
        {!doc.automatic && doc.fallback.length > 0 && (
          <ol className="order-list" aria-label="Fallback order">
            {doc.fallback.map((id, index) => (
              <li key={id}>
                <span>
                  <strong>{label(id)}</strong>
                  {byId.get(id)?.needs_key && !byId.get(id)?.key_saved && <small>No key yet, so it is skipped.</small>}
                </span>
                <span className="key-actions">
                  <button onClick={() => move(index, -1)} disabled={index === 0} aria-label={`Move ${label(id)} earlier`}>
                    Earlier
                  </button>
                  <button onClick={() => move(index, 1)} disabled={index === doc.fallback.length - 1} aria-label={`Move ${label(id)} later`}>
                    Later
                  </button>
                  <button onClick={() => write(doc.fallback.filter((one) => one !== id))} aria-label={`Stop asking ${label(id)}`}>
                    Remove
                  </button>
                </span>
              </li>
            ))}
          </ol>
        )}
        <div className="order-actions">
          {addable.length > 0 && (
            <Select
              label="Add a fallback"
              value=""
              options={[{ value: '', label: 'Add a provider…' }, ...addable.map((row) => ({ value: row.id, label: row.label }))]}
              onChange={(value) => value && write([...doc.fallback, value])}
            />
          )}
          {!doc.automatic && (
            <button className="btn ghost" onClick={() => void save({ search_fallback: '' })}>
              Back to automatic
            </button>
          )}
        </div>
      </div>

      <ul className="key-list" aria-label="Search providers">
        {doc.providers.map((row) => (
          <ProviderItem key={row.id} row={row} result={tested[row.id]} onTest={() => void test(row.id)} />
        ))}
      </ul>
    </section>
  )
}

function ProviderItem({ row, result, onTest }: { row: SearchProviderRow; result: SearchTest | 'testing' | undefined; onTest: () => void }) {
  return (
    <li className="key" data-present={row.ready}>
      <div className="key-head">
        <span>
          <strong>{row.label}</strong>
          <small>{keyLine(row)}</small>
        </span>
        <span className="key-actions">
          <button onClick={onTest} disabled={result === 'testing'} aria-label={`Test ${row.label}`}>
            {result === 'testing' ? 'Testing…' : 'Test'}
          </button>
        </span>
      </div>
      <small className="key-result">{row.note}</small>
      <small className="key-result">{healthLine(row.health)}</small>
      {result && result !== 'testing' && <TestResult result={result} />}
    </li>
  )
}

function TestResult({ result }: { result: SearchTest }) {
  if (!result.ok) return <small className="test-result" data-ok="false">{result.error || 'It did not answer.'}</small>
  return (
    <div className="test-result" data-ok="true">
      <small>
        Answered in {(result.ms / 1000).toFixed(1)} s with {result.results.length} {result.results.length === 1 ? 'result' : 'results'} for “{result.query}”.
      </small>
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
