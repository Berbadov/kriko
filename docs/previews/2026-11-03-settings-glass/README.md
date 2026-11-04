# Settings drawer, in glass, with icons

The reader asked: "redesign the desktop apps settings section". Clarified:
match the new glass look, and remove sub-lines so a row is a label and one
control. After review: "less words more icons, dynamic icons. and there is a
bug. left of the settings panel isn't blurred like the rest."

These screens are the Settings drawer of `kriko-ui/` drawn from its demo data
(`?demo`, no engine), taken with Playwright and Chromium. Motion was set to
reduce so each frame is settled.

## The bug: the left edge was not blurred

Cause: the scrim, which dims and blurs everything behind a drawer, was given
`left: offset + 20` in `Drawer.tsx`. That is the drawer's own left edge, so the
20px strip beside the sheet kept a sharp, undimmed picture while the rest of the
window was blurred. It was in every drawer. It showed most in Settings because
the sheet is now glass and the seam sits against it. It was not width specific.

Fix: the scrim is `inset: 0` and the drawer no longer sets its position, so it
covers every edge. The blur also gets the `-webkit-` prefix a WebKit window
needs.

| Before | After |
|---|---|
| `bug-before-760-dark.png` | `bug-after-760-dark.png` |
| `bug-before-1280-light.png` | `bug-after-1280-light.png` |

All four are the whole window. In the "before" pair a bright sharp strip runs
down the left edge. In the "after" pair it is gone. The demo banner at the top
is above the scrim by design and is not part of this bug.

`tests/drawer_scrim.test.mjs` holds the cause: the scrim covers every edge,
carries both blur properties, and the drawer cannot narrow it. It fails if the
old style comes back (checked). A pixel check of the strip needs a browser, which
the gate does not run, so that was done by hand with the screenshots above.

## The screens

| File | Page | Theme | Window |
|---|---|---|---|
| `01-look-light-wide.png` | Look | light | 1280 wide |
| `02-research-dark-wide.png` | Research | dark | 1280 wide |
| `03-keys-light-wide.png` | Keys | light | 1280 wide |
| `04-connections-dark-wide.png` | Connections | dark | 1280 wide |
| `05-usage-light-compact-760.png` | Usage | light | 760 wide (compact) |
| `06-research-dark-narrow-440.png` | Research | dark | 440 wide |
| `07-tooltip-on-hover.png` | a tooltip on an icon choice | light | 1280 wide |
| `08-hint-on-focus.png` | a hint opened from the keyboard | light | 1280 wide |

All five pages were also drawn in light and dark at 1280, 760 and 560 wide.

## Less words, more icons

* Every row starts with an icon tile, then a name of one or two words, then one
  control. Group headings are one word with an icon: Look, Findings, Chat,
  Effort, Region, Model, Keys, Sharing, Setup, Search, Proxies, Chat apps, Caps,
  Ping, Spent, About.
* The page list is five icons. The chosen page also says its name.
* Facts that used to be a line of text are an icon with a popover (a hint). The
  text opens on hover, on keyboard focus and on press, and it is the button's
  description for a screen reader. Escape closes it.
* State pills stay, in a word or two ("ends a1b2", "Not set", "Needs a key",
  "Automatic", "On, free trial", "4 min ago").

### Every icon-only control, with its accessible name

All are 44px or more and show their name in a tooltip on hover and on keyboard
focus. The chosen one in a choice is filled, drawn heavier and dotted, so it
does not rest on colour.

| Control | Accessible names |
|---|---|
| Page list | Look, Research, Keys, Connections, Usage |
| Theme | System, Dark, Light |
| Motion | Calm, Standard, Vivid (three, two, one lit bars) |
| Doubt (information sensitivity) | Show everything, Hide thin, Strict (each tooltip also says what it does) |
| Tour | Take the tour |
| Chat | Open chat settings |
| Setup | Open setup |
| Agent (after a shared grant) | Choose agent |
| A key | Test, Add or Change, Remove, Save, then the key name, and Cancel |
| A search provider | Test the provider, Move it earlier, Move it later, Stop asking it |
| Proxies | Check the proxies |
| Chat apps | Copy the start command |
| Updates | Check for updates |
| Switches (tick or dash on the knob) | Reduce motion, Anonymous daily ping, Use proxies for blocked pages |
| Hints | Keys stay here, Password scope, No share pepper, Trial used up, Who can spend your keys, Words sent, Who sees pages, Cost, Costs more, A cap only warns, What the ping sends, Partial price |

Still words, on purpose: the digits 1 to 4 of Products at once, the source chips
(an icon and the engine's word), the selects, and the action buttons Use keys,
Forget, Make code, Copy, Add it, Update (each has an icon).

## Dynamic icons

Each plays once, in 150 to 300ms, through `--tm` (the motion profile).

* Theme: the chosen sun turns into view, the chosen moon tilts into view.
* Motion: the bars of the chosen level rise one after another.
* Any chosen icon pops. A chosen source chip draws its tick with a pop.
* The switch knob draws a tick when on and a dash when off.
* A key's padlock is open until the key is set, then the shackle drops shut.
* The page list: the chosen page slides its name open.
* A provider that answered in the last 30 minutes, with nothing newer failing,
  has a dot that pulses. It is the one thing that loops.
* Tooltips and hints rise in, a disclosure chevron turns, a page change rises.

Reduce motion (the app's setting or the system's) sets every animation and
transition duration to nothing in `base.css`, so each icon shows its final state
and does not move. The pulsing dot then draws once and rests. Checked in the
browser: after a choice, with motion on, the pop, sun, bar and tooltip animations
run and the dot loops. With reduce motion nothing runs and the dot has one
iteration of a microsecond.

## Checked

* Contrast audit on the rendered pixels (text made transparent, the pixel under
  each text box read back as its background): 456 text nodes, five pages, light
  and dark, 1280 and 760 wide, disclosures open. The lowest ratio is 4.84. None
  is under 4.5 and none is under 14px. Icon contrast was not measured apart from
  that.
* Every drawer button has an accessible name, and every control is 44px or more
  except the switch, whose knob is 56 by 34 and whose hit area is padded to 66 by
  44.
* No horizontal scroll at 440 wide, on any page.
* Not checked: Windows and macOS shells (Chromium only), and a real engine (the
  demo data only).
