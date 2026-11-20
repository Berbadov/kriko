import { useEffect, useState } from 'react'
import { useBuyerProfile } from '../../engine/buyer'
import type { PrefsDoc } from '../../engine/settings'
import { Setting, Toggle } from './settingsParts'

/** Chat's own findings settings, drawn as rows for the Research section: what
 *  Chat remembers about the reader, and whether an answer is only the product.
 *  Both are written once and used in every chat. */

export interface ChatSettingsProps {
  doc: PrefsDoc | null
  save: (patch: Record<string, string>) => unknown
}

export function ChatSettings({ doc, save }: ChatSettingsProps) {
  const profile = useBuyerProfile()
  const [about, setAbout] = useState('')

  // The saved words arrive after the first read. Until the reader types, show them.
  useEffect(() => {
    setAbout(profile.profile.about)
  }, [profile.profile.about])

  const productOnly = doc?.chosen.chat_product_only === '1'

  return (
    <>
      <Setting
        label="What Chat remembers about you"
        note="A sentence or two, used in every chat. Nothing written here is asked again."
        stack
        control={
          <>
            <textarea
              className="k-input research-memory"
              value={about}
              onChange={(event) => setAbout(event.target.value)}
              rows={4}
              maxLength={1200}
              aria-label="What Chat should remember about you"
              placeholder="Golf 5, 2008, 1.6 petrol. Winter tyres 205/55 R16. Prefer Michelin, budget around 4.000 TL."
            />
            <span className="research-memory-actions">
              <button type="button" className="k-btn" data-size="sm" disabled={!profile.live || about === profile.profile.about} onClick={() => void profile.save({ ...profile.profile, about })}>
                Save
              </button>
              {profile.saved && <span className="press" data-state="done">Saved. Chat uses it from the next question.</span>}
              {!profile.live && <span className="research-agent-note">This needs the engine, because the notes stay on this computer.</span>}
            </span>
            {profile.problem && <p className="error-note">{profile.problem}</p>}
          </>
        }
      />
      <Setting
        label="Product-only answers"
        note="A brief result: the product, where to buy it, and at most two warnings. Product cards show links and page images when available. The research and checks are the same."
        control={<Toggle label="Product-only answers" on={productOnly} disabled={!doc} onChange={(next) => void save({ chat_product_only: next ? '1' : '0' })} />}
      />
    </>
  )
}
