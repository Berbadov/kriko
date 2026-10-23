import { Checkbox } from '../../arc/checkbox/checkbox'
import { useState } from 'react'
import { NO_FILTERS, useHfStore, type HfFilters, type HfModel, type HfQuant, type HfSort } from '../../engine/hfstore'
import { Icon } from '../Icon'
import { Select } from '../controls'

const SIZES: { label: string; min: number | null; max: number | null }[] = [
  { label: 'Any size', min: null, max: null },
  { label: '2–4B', min: 2, max: 4 },
  { label: '4–9B', min: 4, max: 9 },
  { label: '9–16B', min: 9, max: 16 },
  { label: '16B+', min: 16, max: null },
]

const SORTS: { value: HfSort; label: string }[] = [
  { value: 'downloads', label: 'Most downloaded' },
  { value: 'likes', label: 'Most liked' },
  { value: 'new', label: 'Newest' },
]

const LICENSES = [
  { value: '', label: 'Any licence' },
  { value: 'apache-2.0', label: 'Apache 2.0' },
  { value: 'mit', label: 'MIT' },
  { value: 'llama3.1', label: 'Llama 3.1' },
  { value: 'gemma', label: 'Gemma' },
]

const gb = (bytes: number) => `${(bytes / 1e9).toFixed(1)} GB`
const count = (n: number) => (n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}K` : String(n))
/** A model needs its file in memory and room for the context. */
const OVERHEAD = 1.15

/** Hugging Face models that Ollama can pull, found with filters.
 *  It reads the web when the reader presses a button, and downloads only from a Get button. */
export function HfStore({ vramMb, installed, pulling, onGet }: { vramMb: number | null; installed: string[]; pulling: boolean; onGet: (name: string) => void }) {
  const hf = useHfStore()
  const [filters, setFilters] = useState<HfFilters>(NO_FILTERS)
  const [fits, setFits] = useState(false)
  const [open, setOpen] = useState('')
  const [begun, setBegun] = useState(false)

  /** What the card can hold at 4 bits: about 0.6 GB per billion parameters, and room to run. */
  const vramB = vramMb ? Math.floor(vramMb / 1024 / (0.6 * OVERHEAD)) : null
  const effective = (next: HfFilters, onlyFits: boolean): HfFilters =>
    onlyFits && vramB ? { ...next, max: next.max === null ? vramB : Math.min(next.max, vramB) } : next

  const apply = (next: HfFilters, onlyFits = fits) => {
    setFilters(next)
    setFits(onlyFits)
    void hf.search(effective(next, onlyFits))
  }

  if (!begun) {
    return (
      <button
        className="btn ghost"
        onClick={() => {
          setBegun(true)
          void hf.search(NO_FILTERS)
        }}
      >
        Browse Hugging Face
      </button>
    )
  }

  const size = SIZES.findIndex((one) => one.min === filters.min && one.max === filters.max)

  return (
    <div className="hf">
      <form
        onSubmit={(event) => {
          event.preventDefault()
          apply(filters)
        }}
      >
        <label className="search-field">
          <Icon name="search" size={15} />
          <input type="search" placeholder="Search Hugging Face" aria-label="Search Hugging Face" value={filters.query} onChange={(event) => setFilters({ ...filters, query: event.target.value })} />
        </label>
      </form>

      <div className="hf-filters">
        <span className="choices" role="group" aria-label="Size">
          {SIZES.map((one, at) => (
            <button key={one.label} className="choice" data-on={size === at} onClick={() => apply({ ...filters, min: one.min, max: one.max })}>
              {one.label}
            </button>
          ))}
        </span>
        <div className="hf-selects">
          <Select label="Sort" value={filters.sort} options={SORTS} onChange={(value) => apply({ ...filters, sort: value as HfSort })} />
          <Select label="Licence" value={filters.license} options={LICENSES} onChange={(value) => apply({ ...filters, license: value })} />
        </div>
        {vramB !== null && (
          <Checkbox
            checked={fits}
            onCheckedChange={(next) => apply(filters, next === true)}
            label="Fits my graphics card"
            description={`Up to about ${vramB}B parameters at 4 bits.`}
          />
        )}
      </div>

      {hf.problem && <p className="error-note">{hf.problem}</p>}
      {hf.busy && !hf.items && <p className="panel-note">Reading Hugging Face…</p>}
      {hf.items && hf.items.length === 0 && !hf.busy && <p className="panel-note">Nothing matches. Loosen a filter.</p>}

      <ul className="library hf-list" data-busy={hf.busy}>
        {(hf.items ?? []).map((row) => (
          <HfRow
            key={row.repo}
            row={row}
            open={open === row.repo}
            quants={hf.quants[row.repo]}
            vramMb={vramMb}
            installed={installed}
            pulling={pulling}
            onToggle={() => {
              const next = open === row.repo ? '' : row.repo
              setOpen(next)
              if (next) void hf.openRepo(next)
            }}
            onGet={onGet}
          />
        ))}
      </ul>
    </div>
  )
}

function HfRow({
  row,
  open,
  quants,
  vramMb,
  installed,
  pulling,
  onToggle,
  onGet,
}: {
  row: HfModel
  open: boolean
  quants: HfQuant[] | string | undefined
  vramMb: number | null
  installed: string[]
  pulling: boolean
  onToggle: () => void
  onGet: (name: string) => void
}) {
  const meta = [row.params_b ? `${row.params_b}B` : null, row.license, `${count(row.downloads)} downloads`, row.updated].filter(Boolean).join(' · ')
  return (
    <li className="hf-row" data-open={open}>
      <button className="hf-head" onClick={onToggle} aria-expanded={open}>
        <strong>{row.repo}</strong>
        <small>{meta}</small>
      </button>
      {open && (
        <div className="hf-quants">
          {quants === undefined || quants === 'loading' ? (
            <small>Reading the files…</small>
          ) : typeof quants === 'string' ? (
            <small className="hf-none">{quants}</small>
          ) : (
            quants.map((one) => {
              const has = installed.includes(one.pull)
              const tooBig = vramMb !== null && one.bytes * OVERHEAD > vramMb * 1024 * 1024
              return (
                <div key={one.quant} className="hf-quant">
                  <span>
                    <strong>{one.quant}</strong>
                    <small>
                      {gb(one.bytes)}
                      {vramMb !== null && (tooBig ? ' · more than the card holds' : ' · fits the card')}
                    </small>
                  </span>
                  <button className="choice" data-on={has} disabled={pulling || has} onClick={() => onGet(one.pull)} title={has ? 'Installed' : `Get ${one.pull}`}>
                    {has ? 'Installed' : 'Get'}
                  </button>
                </div>
              )
            })
          )}
        </div>
      )}
    </li>
  )
}
