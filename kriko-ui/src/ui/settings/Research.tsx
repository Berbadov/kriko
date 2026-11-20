import { useEffect, useState, type CSSProperties } from 'react'
import { usePrefsDoc } from '../../engine/settings'
import { AgentsSection } from '../panels/Agents'
import { ChatSettings } from '../panels/Chat'
import { Choice, Section, Setting, SelectField, Toggle } from '../panels/settingsParts'
import type { IconName } from '../Icon'

/** Research, in six sections: who answers, how much effort it spends, where it
 *  looks, the language and market it works in, the findings chat keeps, and which
 *  provider sorts a product. Every save is a key of the same `/api/prefs` document
 *  the engine has always read. */

const PARALLEL = [1, 2, 3, 4].map((n) => ({ value: String(n), label: String(n) }))
const SOURCE_COUNTS = [0, 5, 10, 20, 50]
const LANGUAGES = [
  ['en', 'English'], ['es', 'Spanish'], ['fr', 'French'], ['de', 'German'],
  ['it', 'Italian'], ['pt', 'Portuguese'], ['nl', 'Dutch'], ['pl', 'Polish'],
  ['tr', 'Turkish'], ['ru', 'Russian'], ['ja', 'Japanese'], ['ko', 'Korean'],
  ['zh', 'Chinese'], ['ar', 'Arabic'],
].map(([value, label]) => ({ value, label }))

/** The engine's labels are sentences. The rows need a word, and a sentence for
 *  what the kind of source is. */
const KIND_NAMES: Record<string, string> = {
  forums: 'Forums',
  reviews: 'Reviews',
  recalls: 'Recalls',
  manufacturer: 'Maker pages',
  video: 'Video',
  news: 'News',
}
const KIND_NOTES: Record<string, string> = {
  forums: 'Owner forums and discussion threads, where a fault is often described first.',
  reviews: 'Written reviews from buyers, on shopping and review sites.',
  recalls: 'Official recall and safety notices.',
  manufacturer: "The maker's own product, support and service pages.",
  video: 'Video reviews and tests, on video sites.',
  news: 'News articles and press coverage.',
}
/** The tour's "Where to look" step points at this section. */
const WHERE_TO_LOOK_TOUR = 'source-kinds'

export function Research() {
  const { doc, problem, busy, save, reload } = usePrefsDoc()
  if (!doc) return problem ? <p className="error-note">{problem}</p> : null
  return (
    <>
      {problem && <p className="error-note">{problem}</p>}

      <AgentsSection doc={doc} busy={busy} save={(patch) => void save(patch)} reload={async (fresh) => reload(fresh)} />

      <Section title="How much effort">
        <Setting
          icon="layers"
          label="Products at once"
          note="How many products research works on at the same time. A higher number finishes sooner and makes more calls at once."
          control={<Choice label="Products at once" value={doc.chosen.run_concurrency || '4'} options={PARALLEL} onChange={(value) => void save({ run_concurrency: value })} />}
        />
        <RangeSetting
          icon="search"
          label="Thoroughness"
          value={doc.research.thoroughness}
          note="Higher means more searches for each product, so it costs more."
          onSave={(value) => void save({ kriko_agent_thoroughness: String(value) })}
        />
        <RangeSetting
          icon="shieldcheck"
          label="Validation"
          value={doc.research.validation_sensitivity}
          note="Higher asks for exact quotes and a second source before a detail is kept. It takes longer, and keeps fewer doubtful details."
          onSave={(value) => void save({ kriko_agent_validation_sensitivity: String(value) })}
        />
        <Setting
          icon="docplus"
          label="Extra sources"
          note="Extra pages research reads for each product, beyond the first it finds. 0 reads none. A higher number costs more time and searches."
          control={
            <SelectField
              label="Extra sources"
              value={String(doc.research.sources)}
              options={(SOURCE_COUNTS.includes(doc.research.sources) ? SOURCE_COUNTS : [doc.research.sources, ...SOURCE_COUNTS]).map((n) => ({ value: String(n), label: String(n) }))}
              onChange={(value) => void save({ research_sources: value })}
            />
          }
        />
      </Section>

      <Section
        title="Where to look"
        tour={WHERE_TO_LOOK_TOUR}
        note="At least one kind stays on. With none on, research has nowhere to look, so the last one cannot be turned off."
      >
        {doc.source_kinds.map((kind) => {
          const on = doc.research.kinds.includes(kind.id)
          return (
            <Setting
              key={kind.id}
              icon={KIND_ICONS[kind.id] ?? 'globe'}
              label={KIND_NAMES[kind.id] ?? kind.id}
              note={KIND_NOTES[kind.id] ?? 'Pages of this kind.'}
              control={
                <Toggle
                  label={KIND_NAMES[kind.id] ?? kind.id}
                  on={on}
                  disabled={on && doc.research.kinds.length <= 1}
                  onChange={(next) => {
                    const kinds = next ? [...doc.research.kinds, kind.id] : doc.research.kinds.filter((id) => id !== kind.id)
                    if (kinds.length) void save({ research_source_kinds: kinds.join(',') })
                  }}
                />
              }
            />
          )
        })}
      </Section>

      <Section title="Language and market">
        <Setting
          icon="chat"
          label="Reply in"
          note="The language answers are written in. Automatic leaves the choice to Kriko."
          control={
            <SelectField
              label="Response language"
              value={doc.chosen.local_output_language || 'auto'}
              options={[
                { value: 'auto', label: 'Automatic' },
                ...(doc.chosen.local_output_language && !LANGUAGES.some((one) => one.value === doc.chosen.local_output_language)
                  ? [{ value: doc.chosen.local_output_language, label: doc.chosen.local_output_language }]
                  : []),
                ...LANGUAGES,
              ]}
              onChange={(value) => void save({ local_output_language: value })}
            />
          }
        />
        <Setting
          icon="search"
          label="Search in"
          note="The language research uses when it searches the web."
          control={
            <SelectField
              label="Research language"
              value={doc.chosen.local_search_language || 'en'}
              options={[
                ...(doc.chosen.local_search_language && !LANGUAGES.some((one) => one.value === doc.chosen.local_search_language)
                  ? [{ value: doc.chosen.local_search_language, label: doc.chosen.local_search_language }]
                  : []),
                ...LANGUAGES,
              ]}
              onChange={(value) => void save({ local_search_language: value })}
            />
          }
        />
        <Setting
          icon="pin"
          label="Market"
          note="The country whose shops and prices research looks at. Automatic leaves the choice to Kriko."
          control={
            <SelectField
              label="Market region"
              value={doc.chosen.market_region || 'auto'}
              options={doc.market_regions.map((region) => ({ value: region.id, label: region.label }))}
              onChange={(value) => void save({ market_region: value })}
            />
          }
        />
      </Section>

      <Section title="Findings">
        <ChatSettings doc={doc} save={(patch) => void save(patch)} />
      </Section>

      <Section title="Classification">
        <Setting
          icon="tag"
          label="Classify with"
          note="The provider that sorts a product into its catalog. A provider marked no key needs one in Keys and models first."
          control={
            <SelectField
              label="Product classification"
              value={doc.chosen.classification_provider || 'agent'}
              options={doc.classification_providers.map((provider) => ({
                value: provider.id,
                label: provider.ready ? provider.label : `${provider.label} (no key)`,
              }))}
              onChange={(value) => void save({ classification_provider: value })}
            />
          }
        />
      </Section>
    </>
  )
}

const KIND_ICONS: Record<string, IconName> = {
  forums: 'chat',
  reviews: 'star',
  recalls: 'alert',
  manufacturer: 'building',
  video: 'video',
  news: 'news',
}

/** A dial from 0 to 100, its value beside the slider. `note` says what it costs.
 *  The value is saved when the reader lets go, not on every step. */
export function RangeSetting({
  icon,
  label,
  value,
  note,
  onSave,
}: {
  icon: IconName
  label: string
  value: number
  note?: string
  onSave: (value: number) => void
}) {
  const [draft, setDraft] = useState(value)
  useEffect(() => setDraft(value), [value])
  const commit = () => {
    if (draft !== value) onSave(draft)
  }
  return (
    <Setting
      icon={icon}
      label={label}
      note={note}
      stack
      control={
        <span className="settings-range">
          <input
            className="settings-range-input"
            style={{ '--fill': `${draft}%` } as CSSProperties}
            type="range"
            min={0}
            max={100}
            step={5}
            value={draft}
            aria-label={label}
            aria-valuetext={`${draft}%`}
            onChange={(event) => setDraft(event.currentTarget.valueAsNumber)}
            onPointerUp={commit}
            onKeyUp={commit}
            onBlur={commit}
          />
          <b className="settings-range-value">{draft}%</b>
        </span>
      }
    />
  )
}
