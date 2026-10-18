# Understand the interface design

This page records the design decisions for the desktop app and the browser
extension. The code enforces the rules. Read `docs/STYLE.md` for the writing
rules.

## Motion

The app has one motion setting. The reader finds it in Settings, under
Appearance. The three profiles are Calm, Standard, and Vivid. The profile
changes the distance and the speed of each animation.

Reduce motion is a separate switch. It stops all animation. It has priority
over the profile.

All interface motion is one-shot. It starts, it plays, and it stops. Only five
work indicators repeat while work runs. These are the progress bar, the status
ripple, the live meter, the spinner, and the agent mark. A window that is not
in front does not animate.

The app does not draw a click ripple. A control shows its own press and hover
feedback.

A page change slides the content. The direction follows the rail order. A move
to a later tab enters from the right. A move to an earlier tab enters from the
left.

Each page assembles in sections. The sections rise in order. The delay is
short. The page does not move again after it settles.

## Colour and theme

The interface uses one palette of names. Each screen paints through the theme.
The theme maps each name at paint time. Raw colour is not permitted in a
screen.

The light theme swaps the values of the palette. The ground becomes a cool
light grey, panels stay white, and the ink becomes dark. The brand stays blue.

The theme follows the system setting. The reader can select System, Light, or
Dark in Settings.

Two colour groups do not follow the theme. These are the measured sky ink and
the words on the brand blue. A separate fixed path paints them. The hero band
is the third: it is a picture, and it keeps its own dark colours in both
themes. Its base gradient used to follow the theme, and on the light ground it
became a white-to-white smear under a dark image with light words on it.

### Two edges

A hairline is a rule inside one surface. It separates without shouting, and it
is right for a table row or a list item.

A surface boundary is a different thing. The rail against the page, a panel
against the ground, a header against the body under it: these need `EDGE`. A
hairline there disappears on a bright screen and leaves the window with no
shape at all. `EDGE_STRONG` is for the boundary of a control, because a
control's outline is what says it is a control.

## Chat

Chat is the main screen. It has three parts: the thread rail, the conversation,
and the composer.

The empty state shows the agent mark, one short greeting, and a row of prompt
buttons. A prompt button fills the composer.

A reader turn is on the right. An agent turn is on the left, with the agent
mark and the agent name.

The rail is one panel and the conversation is another. Each carries `EDGE`.
The composer sits on the conversation panel, so its own rule is an `EDGE`.

A live phase shows what the agent does: Thinking, Searching, Reading, Writing,
or Citing. The phase mark moves with the phase. Waiting rests.

One status line. The mark, the phase word, and the engine's own line used to
say what was happening at the same time, in different words, side by side. A
reader watching two spinners cannot tell which one to believe.

The answer is markdown. A bold term is bold. A bullet list is a list. A table
is a table. An asterisk in a part number stays an asterisk: the parser only
recognises a construct it can close.

An answer is selectable. A drag takes words out of it, across a bullet and
into the paragraph under it, because the transcript holds one selection rather
than one per block. A link inside an answer opens the page it names.

A selectable run measures its own height. It draws on a canvas, so nothing else
in the tree knows how tall it is, and asking the parent for the parent's height
resolves to zero in a column with no fixed height. That defect shipped once: the
compile, the unit tests and every gate stayed green while every answer painted
nothing.

The answer holds a maximum width. A line that runs the whole window is hard to
follow back to its start. The transcript fills the space between its header and
composer and scrolls independently. Chat uses the remaining window height
without a maximum-height cap.

The composer is multi-line. The Send button lights when the field has text. A
Stop button replaces it while a turn runs. The model picker sits in the
composer's footer row.

### Product cards

A turn that read the reader's own catalogues found products. The agent was
always given those rows; the reader saw only prose.

A product card shows the catalogue's own name for the product, the identity it
is recorded under, and how many risks are recorded against it.

A card has three actions. Open reads the product in Browse. Add to Compare
puts it beside the others. Read again looks the product up now, and saves the
result, because a chat answer is a reading of the catalogue at the moment it
was written.

A card is drawn from the turn's own `products` list, never re-derived from the
prose of the answer.

## Navigation and icons

Chat is the first item in the rail. Chat is also the screen that opens at
start.

The rail has four groups: Check, Knowledge, System, and This install. Its expanded
width is 216px; the icon rail remains 68px with 44px navigation targets.

Working page heads share a 104px sky band. The breadcrumb sits above a compact
title and a single-line description, below the window controls. A short fade at
the bottom preserves readable sky ink in both themes.

The active row has a brand wash and a lit left edge. The glyph sits in its own
well and lights with the row. The count and the badge are pills. A row lifts by
one pixel on hover.

The collapsed rail shows the icon wells only. A tooltip gives the label.

The rail uses fourteen glyph files. Each glyph uses a 24-unit box, a 1.7-unit
stroke, round ends, and the current text colour. The file names did not change,
because other screens use the same names.

## Typography

The app embeds two font families. A condensed face is for display text. A sans
face is for body text.

Four ink names carry the text: INK, INK_2, MUTED, and DIM. The light values
keep the same contrast as the dark values.

An eyebrow is semibold and muted. The page title is bold. The lead line is
larger than a label, but smaller than the title.

The interface toolkit has no letter-spacing property. The app makes the
tracking itself. A label uses one span for each letter and a small gap between
the spans. The eyebrow, the table head, and the state tag use this tracking. A
mixed-case label does not, because the tracking breaks its hover colour.

## Spacing

The app uses one 4px scale: 4, 8, 12, 16, 24, and 32. A screen names a step. A
screen does not invent a pixel value.

A button is 40 units high. A pill or a badge is 24 units high. A card has one
inset. A table head has one distance from its first row.

The scale keeps two cards in one row equal. It keeps two controls in one row
equal.

## Sources

A source row has four parts. These are a site mark, the host, the page title,
and a trust mark.

The whole row is a link. A click opens the page in the reader's browser.

The app asks the engine for the site's own icon. The engine fetches the icon
from the site, checks the address first, and keeps a copy for 30 days. The app
then draws the icon in the row. The engine uses no third-party icon service.

If the engine has no icon for a host, the app draws a generated mark from the
host. The reader sees a mark either way.

The trust mark has three states. A check means the source backs the statement.
A bang means the source disputes it. A queue means there is no record.

## Compare

A slot is one product column. The board is a rail of slot cards.

A slot card shows the ordinal, the product, the catalog, a strip of site marks,
and the source count. It has a change control, a clear control, and two
reorder controls.

The table groups its rows into Specs, Evidence, and Availability. Each cell
shows its value and its trust mark. A pinned row carries a small light.

The Differences only switch hides a row when all slots agree.

Every source is an inline row that opens its page. The reader does not open a
second panel to find a source.

The reader can scroll the table rows. The head row stays above the rows. The
attribute column stays at the left edge. The table has no sideways scroll. When
the columns do not fit, they wrap into two bands.

The old freehand drawing board is gone. The word board now means the slot rail.

## Local model store

The store is one card. The toolbar has a search field, four filters, and a
sort control. The filters are Installed, Fits this machine, Small, and All. The
sort orders are Name and Size.

A model is one full-width row, not a tile: a row per model, separated by a
rule. The name is the largest thing in the row. Under it sits one quiet line:
the parameter count, the size on disk, and the quantisation. A row carries at
most two status chips, chosen in order of what the reader needs to know.

A row has one primary action at its right edge: Download, Use, or an In use
tag. Open in library and Remove are quiet, because neither is what the reader
came for. A download uses the shared progress bar and the row shows the current
message and a stop control.

A size picker appears only on a model that is not installed and offers more
than one size, because it chooses what Download fetches.

The store reads the library only when it needs the library. This rule keeps the
screen fast and the network quiet.

An installed model has a Remove action. The action takes two presses. The first
press asks for a confirmation. The second press removes the model. The engine
deletes the model through the local model server.

## Browser extension

The panel and the options page share the palette and the motion profile.

The extension is distributed through the Chrome Web Store. The app's own screen
stages the files and shows the two manual steps; it does not claim to have
installed anything.

The status turns Connected only after the extension reaches the engine. The
screen does not claim success.

The panel has a light theme and a dark theme. The options page follows the same
selection.

## Text motion

An answer arrives block by block. Each block takes its final place at once,
then fades and rises in one short stagger. A long answer still settles in well
under a second.

Cylinder status shows one line in a fixed window. When the line changes, the
old line moves up and out. The new line moves in from below. The same text does
not replay.

## Sky

The sky band has two motions. Scroll parallax moves the band by a fraction of
the page scroll. A short awakening drifts the light fields when the page
arrives, then stops.

The sky does not repeat. An idle window draws no sky frames.

## Rules that the code enforces

The code permits raw colour only in the theme module.

The code permits a loop only in the five work indicators.

The code permits a bare address in a link only for `http`, `https` and
`mailto`. A markdown answer is model output, and a `javascript:` or `file:`
target is not something a reader asked to open.

The window makes one motion decision for each frame. The decision comes from
the reader setting and the window state.

Each card has a header glyph.

Every screen reads the shared card header.

The extension text holds zero em dashes and zero informal phrases.

## Limits

The table head stays with the table body. It does not stay on screen when the
reader scrolls the whole page. The interface toolkit has no pinned position for
a page.

A nested scroll area holds the wheel while the pointer is over it.

The app does not decode an icon of the older ICO type. The engine converts the
ICO to PNG first. If no PNG frame is present, the app draws the generated mark.

The app asks for an icon only for a host that a screen already shows. It does
not scan a site.

The direct install opens a separate browser profile. The reader sees the note
before the window opens.
