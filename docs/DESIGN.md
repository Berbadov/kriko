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

The light theme swaps the values of the palette. The ground becomes white. The
ink becomes dark. The brand stays blue.

The theme follows the system setting. The reader can select System, Light, or
Dark in Settings.

Two colour groups do not follow the theme. These are the measured sky ink and
the words on the brand blue. A separate fixed path paints them.

The caution tone has its own name. The light theme makes it darker. An
unmapped amber was too bright on the white ground.

Body text holds a contrast of at least 4.5 to 1. The page title holds a
contrast of at least 7 to 1 against the sky.

## Navigation and icons

Chat is the first item in the rail. Chat is also the screen that opens at
start.

The rail has four groups: Check, Knowledge, System, and This install.

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

A model tile shows the name, the parameter count, the size on disk, and a
quantisation chip. It shows an Installed badge and a Fits badge.

A tile has a primary action and a secondary action. The primary action is
Download, Use, or In use. The secondary action opens the library page.

A download uses the shared progress bar. The tile shows the current message and
a stop control.

The store reads the library only when it needs the library. This rule keeps the
screen fast and the network quiet.

An installed model has a Remove action. The action takes two presses. The first
press asks for a confirmation. The second press removes the model. The engine
deletes the model through the local model server.

## Chat

Chat is the main screen. It has three parts: the thread rail, the conversation,
and the composer.

The empty state shows the agent mark, one short greeting, and a row of prompt
buttons. A prompt button fills the composer.

A reader turn is on the right. An agent turn is on the left, with the agent
mark and the agent name.

A live phase shows what the agent does: Thinking, Searching, Reading, Writing,
or Citing. The phase mark moves with the phase. Waiting rests.

The answer uses word reveal. The current step uses cylinder status. A cited
source is a clickable row.

The composer is multi-line. The Send button lights when the field has text. A
Stop button replaces it while a turn runs. A small picker selects the model.

## Browser extension

The panel and the options page share the palette and the motion profile.

The install path has one button: Add to browser. One action stages the files
and opens a browser that already has the extension.

The status turns Connected only after the extension reaches the engine. The
button does not claim success.

The manual steps appear only when the direct action cannot run. The reader
does not see two install paths at the same time.

The panel has a light theme and a dark theme. The options page follows the same
selection.

## Text motion

Word reveal gives each word its final place at once. The word then fades and
rises in a short stagger. A long sentence still settles in less than one
second.

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
