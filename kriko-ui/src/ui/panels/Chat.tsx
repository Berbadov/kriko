import { useEffect, useState } from 'react'
import { useBuyerProfile } from '../../engine/buyer'
import { usePrefsDoc } from '../../engine/settings'
import { Switch } from '../controls'

/** Chat's own settings: what the agent remembers about the reader, and the
 *  shape of a buying answer. Both are written once and used in every chat. */
export function ChatPanel(_: { onOpen?: (lookupId: string) => void }) {
  const profile = useBuyerProfile()
  const { doc, problem, save } = usePrefsDoc()
  const [about, setAbout] = useState('')

  // The saved words arrive after the first read. Until the reader types, show them.
  useEffect(() => {
    setAbout(profile.profile.about)
  }, [profile.profile.about])

  const productOnly = doc?.chosen.chat_product_only === '1'

  return (
    <div className="panel-body">
      <section className="panel-group">
        <h3>Before it answers</h3>
        <p className="panel-note">
          When one detail would change the answer (a tyre size, a model year, the market), Chat asks for it first, with
          choices. It asks only what your notes below cannot settle.
        </p>
      </section>

      <section className="panel-group">
        <h3>What it remembers about you</h3>
        <p className="panel-note">Used in every chat. The same notes as For you.</p>
        <label className="need-field">
          <span>
            Your words
            <small>A sentence or two. Nothing written here is asked again.</small>
          </span>
          <textarea
            value={about}
            onChange={(event) => setAbout(event.target.value)}
            rows={4}
            maxLength={1200}
            aria-label="What Chat should remember about you"
            placeholder="Golf 5, 2008, 1.6 petrol. Winter tyres 205/55 R16. Prefer Michelin, budget around 4.000 TL."
          />
        </label>
        <button
          className="btn"
          disabled={!profile.live || about === profile.profile.about}
          onClick={() => void profile.save({ ...profile.profile, about })}
        >
          Save
        </button>
        {profile.saved && <p className="panel-note" data-ok="true">Saved. Chat uses it from the next question.</p>}
        {!profile.live && <p className="panel-note">This needs the engine, because the notes stay on this computer.</p>}
        {profile.problem && <p className="error-note">{profile.problem}</p>}
      </section>

      <section className="panel-group">
        <h3>Answers</h3>
        <div className="setting">
          <span>
            Product-only answers
            <small>
              Same product research and checks, with a brief result: the product, where to buy it, and at most two warnings. Product cards show links and page images when available.
            </small>
          </span>
          <Switch
            label="Product-only answers"
            on={productOnly}
            onChange={(next) => void save({ chat_product_only: next ? '1' : '0' })}
          />
        </div>
        {problem && <p className="error-note">{problem}</p>}
      </section>
    </div>
  )
}
