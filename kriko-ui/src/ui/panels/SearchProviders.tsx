import { useSearchProviders, type SearchHealth, type SearchProviderRow, type SearchTest } from '../../engine/websearch'
import { Select } from '../controls'
import { Icon } from '../Icon'
import { Group, Hint, IconButton, Row, State } from './settingsParts'
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

/** What the reader needs to judge a provider: when it last answered and how often it has not.
 *  The row shows the short form. The whole line is its hover text. */
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

function healthShort(health: SearchHealth): string {
  if (!health.calls) return 'Not used yet'
  return health.last_success ? ago(health.last_success) : 'No answer yet'
}

function keyState(row: SearchProviderRow): { text: string; tone: 'ok' | 'warn' | 'none' } {
  if (!row.needs_key) return { text: 'No key', tone: 'none' }
  return row.key_saved ? { text: 'Key set', tone: 'ok' } : { text: 'Needs a key', tone: 'warn' }
}

/** A trouble is shown while it is the latest word: a failure newer than the last answer. */
function troubleLine(health: SearchHealth): string {
  if (!health.last_failure || !health.last_problem) return ''
  if (health.last_success && health.last_success > health.last_failure) return ''
  return `Trouble ${ago(health.last_failure)}: ${health.last_problem}`
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
    <Group
      icon="search"
      title="Search"
      tour="web-search"
      hint={
        <Hint icon="cloudup" title="Words sent">
          A hosted provider receives the words you search.
        </Hint>
      }
    >
      {problem && <p className="error-note">{problem}</p>}

      <Row icon="search" label="First">
        <Select
          label="First search provider"
          value={doc.primary}
          options={doc.providers.map((row) => ({ value: row.id, label: row.needs_key && !row.key_saved ? `${row.label} (no key)` : row.label }))}
          onChange={(value) => void save({ search_provider: value })}
        />
      </Row>

      <Row icon="swap" label="Then" state={doc.automatic ? <State>Automatic</State> : undefined}>
        {addable.length > 0 && (
          <Select
            label="Add a fallback"
            value=""
            options={[{ value: '', label: 'Add…' }, ...addable.map((row) => ({ value: row.id, label: row.label }))]}
            onChange={(value) => value && write([...doc.fallback, value])}
          />
        )}
      </Row>
      {!doc.automatic && doc.fallback.length > 0 && (
        <ol className="order-list" aria-label="Fallback order">
          {doc.fallback.map((id, index) => (
            <li key={id}>
              <span className="key-name">
                <strong>{label(id)}</strong>
                {byId.get(id)?.needs_key && !byId.get(id)?.key_saved && <State tone="warn" icon="lock">No key</State>}
              </span>
              <span className="key-actions">
                <IconButton icon="send" label={`Move ${label(id)} earlier`} onClick={() => move(index, -1)} disabled={index === 0} />
                <IconButton icon="down" label={`Move ${label(id)} later`} onClick={() => move(index, 1)} disabled={index === doc.fallback.length - 1} />
                <IconButton icon="x" label={`Stop asking ${label(id)}`} tone="danger" onClick={() => write(doc.fallback.filter((one) => one !== id))} />
              </span>
            </li>
          ))}
        </ol>
      )}
      {!doc.automatic && (
        <Row actions>
          <button className="btn" onClick={() => void save({ search_fallback: '' })}>
            <Icon name="retry" size={18} />
            Automatic
          </button>
        </Row>
      )}

      <ul className="key-list" aria-label="Search providers">
        {doc.providers.map((row) => (
          <ProviderItem key={row.id} row={row} result={tested[row.id]} onTest={() => void test(row.id)} />
        ))}
      </ul>
    </Group>
  )
}

/** A provider is answering when it has answered lately and nothing newer has failed. */
function answering(health: SearchHealth): boolean {
  if (!health.last_success) return false
  if (health.last_failure && health.last_failure > health.last_success) return false
  return Math.round(Date.now() / 1000) - health.last_success < 1800
}

function ProviderItem({ row, result, onTest }: { row: SearchProviderRow; result: SearchTest | 'testing' | undefined; onTest: () => void }) {
  const key = keyState(row)
  const trouble = troubleLine(row.health)
  return (
    <li className="key" data-present={row.ready} title={healthLine(row.health)}>
      <div className="key-head">
        <span className="key-name">
          <span className="row-icon" data-tone={row.ready ? 'ok' : undefined} aria-hidden="true">
            <Icon name="search" size={20} />
            {answering(row.health) && <i className="live-dot" />}
          </span>
          <strong>{row.label}</strong>
          <State tone={key.tone}>{key.text}</State>
          {row.health.calls > 0 && <State>{healthShort(row.health)}</State>}
        </span>
        <span className="key-actions">
          <IconButton icon="play" label={result === 'testing' ? `Testing ${row.label}` : `Test ${row.label}`} onClick={onTest} disabled={result === 'testing'} />
        </span>
      </div>
      {trouble && <small className="key-result" data-tone="risk">{trouble}</small>}
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
