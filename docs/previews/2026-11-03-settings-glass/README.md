# Settings drawer, in glass

The reader asked: "redesign the desktop apps settings section". Clarified:
match the new glass look, and remove sub-lines so a row is a label and one
control.

These screens are the Settings drawer of `kriko-ui/` drawn from its demo data
(`?demo`, no engine), taken with Playwright and Chromium. Motion was set to
reduce so each frame is settled.

| File | Page | Theme | Window |
|---|---|---|---|
| `01-look-light-wide.png` | Look | light | 1280 wide |
| `02-research-dark-wide.png` | Research | dark | 1280 wide |
| `03-keys-light-wide.png` | Keys | light | 1280 wide |
| `04-connections-dark-wide.png` | Connections | dark | 1280 wide |
| `05-usage-light-compact-760.png` | Usage | light | 760 wide (compact) |
| `06-research-dark-narrow-440.png` | Research | dark | 440 wide (the page list wraps) |

All five pages were also drawn in light and dark at 1280, 760 and 560 wide,
and a contrast audit read every text node of the drawer (see below).

## What a row is now

A row is a label on the left and one control on the right, never shorter than
56px. Beside the label there may be a state pill (for example "Set, ends
a1b2", "Needs a key", "Automatic"). The grey line under a label is gone.

Notes that stay are one short line each, with a dot, and only where a setting
sends data off the machine, costs money, or warns:

| Where | Note |
|---|---|
| Research, Thoroughness | Higher means more search calls. |
| Keys | Keys stay on this computer. The engine never sends one back. |
| Shared access | The password works in this app only. Keys are sealed on this computer. |
| Shared access, friend fold | Send the code and the password in two messages. Anyone with both can spend your keys. Replace the keys at the provider to stop a code. |
| Web search | A hosted provider receives the words you search. |
| Proxies | A proxy sees which pages you read, and a site's terms may forbid it. The choice is yours. |
| Chat clients | Lookups are free. A chat answer uses your agent. |
| Usage caps | A cap only warns. Nothing is blocked. |
| Daily ping | Once a day: a random install id and the app version, nothing else. Privacy policy link. |
| Daily ping, no endpoint | No endpoint is set, so nothing leaves this computer. |
| Spent | N runs have no price, so the amount is partial. |

Warnings and errors stay too: the missing share pepper, a proxy switched on
with no address, a used-up trial, demo numbers, update problems, key and
search test results, and every `error-note`.

Text that moved out of the row and is still there: the three meanings of
"How much doubt to show" are the hover text of each choice, the long proxy
explanation and each chat client's setup note sit in a closed disclosure row,
and a search provider's health line is the hover text of its row (the short
form, "Answered 4 min ago", shows as a pill).

Text removed with no replacement: the description under Tour, Chat settings,
Set up Kriko, Products at once, Extra sources, Response language, Research
language, Market region, Product classification, endpoint and model,
Validation sensitivity, the engine's description of each search provider, the
intro paragraphs of Web search, Proxies and Chat clients, the "Low" and "High"
ends of a dial, the long paragraph under Shared access, and the notes under
each access field.

## Look

* Each group is a translucent surface with a bright 1px rim, a hairline
  outside the rim, a 24px radius, a soft shadow and a backdrop blur. Where the
  platform has no backdrop blur the group is the solid `--gl-solid`.
* The drawer is a 28px glass sheet over a soft gradient of the brand hues.
* The page list is a sticky glass bar. It wraps to two lines under 400px.
* Atkinson Hyperlegible (SIL Open Font Licence) is bundled from
  `@fontsource/atkinson-hyperlegible`, so nothing loads from the network. Body
  text is 15px, no text is under 14px, headings are sentence case.
* A chosen choice is a solid blue fill, a chosen chip also carries a tick, so
  no state rests on colour alone.
* Motion is a 220ms rise on a page change and 150 to 180ms on controls. It
  reads `--tm`, so reduce motion stops it.

## Checked

* Contrast audit on the rendered pixels (text made transparent, the pixel
  under each text box read back as its background): 728 text nodes over five
  pages, light and dark, 1280 and 760 wide, disclosures open. The lowest ratio
  is 4.58, none is under 4.5, none is under 14px.
* No horizontal overflow at 440 wide.
* Not checked: Windows and macOS shells (the page was drawn in Chromium
  only), and a real engine (the demo data only).
