import { usePrefsDoc } from '../../engine/settings'
import { showSettingsPage } from '../panels/settingsPages'
import { Section, Setting, State } from '../panels/settingsParts'
import { KeysGroup, ModelGroup, SharedAccessGroup } from './parts'

/** Keys and models, in the order a reader needs them: the provider keys, sharing
 *  someone's keys, the model endpoint, and one row that points to Local AI. */
export function Keys() {
  return (
    <>
      <KeysGroup />
      <SharedAccessGroup />
      <ModelGroup />
      <LocalModelRow />
    </>
  )
}

/** The model on this computer has its own section. This row says which one is in
 *  use, from the saved setting alone, so nothing is asked of the computer here. */
function LocalModelRow() {
  const { doc } = usePrefsDoc()
  const chosen = doc?.chosen.local_model ?? ''
  return (
    <Section title="On this computer">
      <Setting
        icon="cpu"
        label="Local model"
        note="Run research on a model on this computer, free of charge. Set it up in Local AI."
        value={<State tone={chosen ? 'ok' : 'none'}>{chosen || 'None chosen'}</State>}
        control={
          <button type="button" className="k-btn" onClick={() => showSettingsPage('local')}>
            Open Local AI
          </button>
        }
      />
    </Section>
  )
}
