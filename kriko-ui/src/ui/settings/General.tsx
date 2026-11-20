import { useState } from 'react'
import { usePrefs, type Profile, type ThemePref } from '../../prefs'
import { useSensitivity } from '../../engine/sensitivity'
import type { Sensitivity } from '../../engine/thinness'
import { startTour } from '../../tour/Tour'
import { showDrawer } from '../drawerEvents'
import { Choice, IconButton, Section, Setting, ThemePicker, Toggle } from '../panels/settingsParts'
import { useTextFont, type TextFont } from './font'

const THEMES: { value: ThemePref; label: string }[] = [
  { value: 'system', label: 'System' },
  { value: 'dark', label: 'Dark' },
  { value: 'gray', label: 'Gray' },
  { value: 'paper', label: 'Paper' },
  { value: 'white', label: 'White' },
]
const FONTS: { value: TextFont; label: string }[] = [
  { value: 'default', label: 'Default' },
  { value: 'atkinson', label: 'Accessibility' },
]
const PROFILES: { value: Profile; label: string }[] = [
  { value: 'calm', label: 'Calm' },
  { value: 'standard', label: 'Standard' },
  { value: 'vivid', label: 'Vivid' },
]
/** The three choices for findings with doubt. The note says what the two
 *  narrowing choices do, in one sentence. */
const SENSITIVITY: { value: Sensitivity; label: string }[] = [
  { value: 'all', label: 'Show all' },
  { value: 'hide_thin', label: 'Hide uncertain' },
  { value: 'strict', label: 'Only confirmed' },
]

/** Looks, the tour, findings, and chat. The first page a reader meets. */
export function General() {
  const { theme, setTheme, profile, setProfile, reduce, setReduce } = usePrefs()
  const { sensitivity, choose } = useSensitivity()
  const [font, setFont] = useTextFont()
  const [sensitivityProblem, setSensitivityProblem] = useState('')

  return (
    <>
      <Section title="Appearance">
        <Setting
          icon="palette"
          label="Theme"
          stack
          note="System follows this computer. Dark and Gray are dark; Paper and White are light."
          control={<ThemePicker label="Theme" value={theme} options={THEMES} onChange={setTheme} />}
        />
        <Setting
          icon="book"
          label="Text font"
          note="Accessibility uses Atkinson Hyperlegible, a face built so that similar letters look different."
          control={<Choice label="Text font" value={font} options={FONTS} onChange={setFont} />}
        />
        <Setting
          icon="gauge"
          label="Motion"
          note="Calm moves less and more slowly. Vivid moves more and more quickly."
          control={<Choice label="Motion" value={profile} options={PROFILES} onChange={setProfile} />}
        />
        <Setting
          icon="pause"
          label="Reduce motion"
          note="Stops the movement in the app. Your computer's own reduce-motion setting does the same."
          control={<Toggle label="Reduce motion" on={reduce} onChange={setReduce} />}
        />
      </Section>

      <Section title="Findings">
        <Setting
          icon="eye"
          label="Doubtful findings"
          note="Hide uncertain hides findings with two or more reasons for doubt, and counts them; Only confirmed keeps just those with no reason for doubt."
          control={
            <Choice
              label="Doubtful findings"
              value={sensitivity}
              options={SENSITIVITY}
              onChange={(value) => void choose(value).then(setSensitivityProblem)}
            />
          }
        />
        {sensitivityProblem && <p className="error-note">{sensitivityProblem}</p>}
      </Section>

      <Section title="Help and chat">
        <Setting
          icon="compass"
          label="Take the tour"
          note="A short walk through the screens, one thing at a time."
          control={<IconButton icon="play" label="Take the tour" onClick={startTour} />}
        />
        <Setting
          icon="chat"
          label="Chat settings"
          note="Options for chat, kept in their own panel."
          control={<IconButton icon="expand" label="Open chat settings" onClick={() => showDrawer('chat')} />}
        />
      </Section>
    </>
  )
}
