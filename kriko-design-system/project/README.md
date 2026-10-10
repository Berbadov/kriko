KRIKO is a local product research app that produces knowledge: claims tied to evidence and sources, stored in SQLite, one file per product, on one calm, dark surface that stays quiet until something needs a human. It has one loud colour, blue, one display voice, condensed capitals, and soft translucent controls. Build screens that look like an instrument panel, not a SaaS template.

## Content fundamentals

Write plain, sentence-case product English; the voice is quiet and factual and addresses the user as "you" and "your" ("Waiting for your decision on product A before completing synthesis."). Display type is the exception: page titles, card titles, button labels and nav items are set in uppercase condensed capitals (HOME, AGENTS, NEW ORDER) while the words under them stay sentence case. The name is KRIKO in the wordmark and on the cover, Kriko in running copy.

Use these rules:

- Page titles are one or two words; the line under each is one `lead` sentence starting with a verb: "Monitor orders, trust signals, and agent activity from one operational view."
- Buttons are a verb or verb and noun: NEW ORDER, ADD AGENT, RESCAN, RUN BENCHMARK, SAVE CHANGES. No exclamation marks, no emoji.
- State is a word, never a colour alone: LIVE, NEEDS YOU, QUEUED, DONE, BLOCKED. Say "needs you" when the system waits on the user, never "attention required".
- Kriko produces knowledge and never gives an opinion. Never recommend, rate, rank, score or highlight a best product, and never show a verdict, a winner or a confidence figure about a product. Trust words describe evidence for a claim, not the product. Compare lays products side by side and marks only where they differ.
- Say what is stored and where: "Wrote 12 claims to product-a.sqlite", "Writes to its own SQLite file".
- Agent task lines are lowercase mono fragments joined by a middle dot: `compare · gemini-2.5-flash`, `76% · fetching review data`.
- Reassure about privacy where data appears: "No data leaves the CLIs for their LLMs.", "All data remains on this machine."
- Numbers carry units and context: `42ms latency`, `100% uptime`, `26 in total · 7 days`.

## Visual foundations

One hue, many lightnesses. `brand` (`#1f4fff`) is the identity and the only large colour: the flat top-bar band, the primary button, the NEEDS YOU tag, active nav and the cover. Everything else is navy-black ground, translucent white glass, and blues that step by lightness: `brand-deep` for dark fields, `brand-bright` for blue text, `ice` for the lightest accent. Never use `brand` for body text on dark; use `brand-bright`. `danger` coral is the only other hue and appears only for stop, blocked and failed.

Two materials, never mixed on one element. Surfaces are glass: flat, translucent and quiet. Controls and indicators are hardware: graphite plates, a blue key, recessed wells and LEDs, with real depth.

Pages open with a hero: a dithered blue sky image (`assets/Sky`) behind a 96px condensed title and one lead sentence, with the clouds on the right and the left kept clear so white text always sits on `brand` blue. The dither itself fades the image into `ground`, so there is no gradient overlay. The sky can move: leaf shadows drift over it (see `Motion.md`, baked with `assets/Sky/shimmer.py`). One pale frosted card (`FROST`, dark `#05070f` text) may float over a hero to hold the page's main action: the check box on Home, the test prompt on Local LLM. It is the only light surface in the app; the app is built for GPUI, which cannot blur, so frost is a translucent fill over the soft sky, not a blur.

Surfaces are glass, not boxes. Stack `ground`, `surface-1` for the rails, then `glass-1` cards with a 16px backdrop blur, `glass-2` for secondary buttons and inputs, `glass-3` for hover and pressed. Separate rows with a `hairline`; give controls a `border-control` outline when they need an edge. No coloured borders, no side accents, no shadow on a glass card; `shadow-lift` is for floating menus.

Type has three voices: `display`, `h1`, `h2`, `label` in Barlow Condensed uppercase; `lead`, `body`, `body-strong`, `caption` in DM Sans; `mono-meta`, `mono-label`, `breadcrumb` in JetBrains Mono for paths, ids, timestamps, tags and column headers. Headline numbers use `metric` with tabular figures.

Buttons are flat. The primary action is a blue **key**, a solid `brand` fill that lightens to `brand-hover` on hover and darkens to `brand-low` while pressed, with no gradient, lip or drop shadow; secondaries are graphite **plates**, a solid `bezel-lo` fill with a 1px `bezel-edge` that lifts to `bezel-hi` on hover; anything that holds a state sits in a recessed **well** (`well`, `shadow-well`): segmented rails, switch tracks, meters, tags and LED tiles. Radii stay soft: `radius-md` for keys and plates, `radius-lg` for cards, `radius-sm` for tags, `radius-pill` for the switch only.

Indicators are LEDs, not dots in pills. A lit square in a state colour with a soft glow (`shadow-led`) in a 5x5 or 8x8 matrix is the only indicator shape, and it is always paired with a word or a glyph that is itself readable: bang for NEEDS YOU, check for DONE, cross for BLOCKED, scanning bars for LIVE. One lit colour per tile. Two-series charts use `ice` and `brand-bright` and differ in lightness; sparklines are 3px ticks with the current period in `ice`; progress is a 24-segment LED meter. The focus ring is a solid 2px `ice` outline offset 3px (13.7:1 on `surface-2`).

Layout is a labelled sidebar and one main column. The sidebar is `surface-1` with a `brand` block at the top holding the white wordmark and the line "local product knowledge", then four groups in `mono-label` capitals (CHECK, KNOWLEDGE, SYSTEM, THIS INSTALL) with 1.5px outline icons; the current item sits in a recessed well with `ice` text, never in a coloured bar. The main column has a `space-7` gutter, a mono breadcrumb, a `display` title, one `lead` sentence, then glass cards on a `space-5` grid, three across for totals. A right-hand rail, 320px wide on every screen, lists the working agents: tile, task line, state word, a segmented meter, the SQLite file each is writing to and the claims it added; an agent that needs you becomes a `brand` card with one action, and the footer repeats that data stays on this machine. State and trust are words with LEDs: LIVE or READING, NEEDS YOU, QUEUED, DONE and BLOCKED for processes, BACKED, DISPUTED and NO EVIDENCE for claims. Empty states and covers may carry a pixel stair or dither made of 16px squares in blue steps (from the Mistral grid and the dithered sky reference); never put texture behind data.

## Motion

Motion explains state and gives feedback; it is never decoration. Keys and plates change colour in 90ms and never move; thumbs and switch knobs slide in 260ms with a small overshoot (`--ease-mech`); LEDs fade in 160ms and boot once on mount with a 600ms flicker; loops (LIVE scan, meter head, NEEDS YOU blink) run only while their state is true. The loading mark is the K jack lifting. Durations and easings are CSS variables in `components/bundle.css`, since the token format has no motion family; `prefers-reduced-motion` removes every loop and flicker. Full rules and the animated mark are in the Motion guidelines.

## Iconography

Icons are 1.5px-stroke outline glyphs with rounded joins at 16-20px, drawn in `muted` and in `brand-bright` when active. Use Lucide equivalents unless the product ships its own set. Glyphs that stand in for icons on controls are 5x5 LED bitmaps (list, grid, columns, wide, play), listed in the LedMatrix guidelines. Every agent gets a 40px AgentIcon tile: the vendor's official icon from `assets/Agents` when supplied, otherwise a 5x5 LED monogram; we never redraw a vendor mark. The KRIKO wordmark and mark live in `assets/Logos`: pick the white file on dark grounds and the brand band, the black file on light, and never redraw or recolour them.

## Using this system

Start from the `ground`, `surface-1` and `glass-*` ladder, then compose from the guidelines for Button, LedMatrix, StatusTag, SegmentedControl, Toggle, ProgressBar, AgentIcon, AgentRow, MetricCard, Callout, TopBar and Motion, and load `components/bundle.css` for the classes and motion variables. All 14 tabs are drafted as full screens in the Pages group. Motion is specified in `Motion.md` and demonstrated in the MotionLab card. The app is moving to GPUI: `Gpui.md` and `gpui/theme.rs` hold the handoff. For a pattern not listed (table, nav rail, chart) follow the same rules: glass fills, hairline rows, uppercase condensed titles, words for state, one blue.

## Web: site and marketplace

Two dummy pages in the `Web` group show where the project goes next, both 1440 wide on the same tokens. `SiteLanding` is the presentation site for the GitHub project: sky hero, the five-step run on a dark stage (the live lab scene goes there), what Kriko writes, screenshot slots, three rules and downloads. `SiteMarketplace` is the data pack browser. A pack describes what to look for in one kind of product (attributes, claim types, site hints) and holds no findings, so the marketplace follows the same neutrality rule as the app: no stars, ratings, download counts or popularity sort, only name, date and size. Trust words on a pack describe the file (SIGNED, UNSIGNED, DRAFT), never its quality. Both are placeholders: copy, sizes, file names and every pack except `samsung.headphones` are invented, and there are no vendor logos until official files are supplied.
