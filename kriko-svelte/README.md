# Svelte + TypeScript

The `svelte/` folder is a Svelte 5 (runes) and TypeScript port of the components and the five example pages. It checks clean with `svelte-check` in strict mode, and every file compiles. The components are thin: all looks come from `components/bundle.css` and the tokens, so a class name in a preview is the same class name in Svelte.

## Set up

1. Copy `svelte/` into `src/lib/kriko/` (SvelteKit) or `src/` (Vite). Pages import the wordmark from `../assets/kriko-wordmark-white.svg`; copy that file from `assets/Logos` and adjust the path if your folders differ.
2. Import the styles once, in the root layout or `main.ts`, in this order: `tokens.css` (compiled from `tokens.json`, see Consuming this system below), then `components/bundle.css`.
3. Load the three fonts: `@fontsource/barlow-condensed` (600, 700), `@fontsource/dm-sans` (400, 600) and `@fontsource/jetbrains-mono` (400, 600).
4. Add a `*.svg` module declaration (`declare module '*.svg' { const src: string; export default src }`) if your template does not have one.

## What is in the folder

| File | Role |
| --- | --- |
| `lib/types.ts` | `TagState`, `VerdictKind`, `NavItem`, `NavGroup`, `AgentInfo`, `Product` |
| `lib/glyphs.ts` | 5x5 LED bitmaps and the monogram letters |
| `lib/nav.ts` | the real navigation as data: Check, Knowledge, System, This install |
| `lib/sample.ts` | sample data, replace with reads from the local store |
| `Led`, `Key`, `Tag`, `Verdict`, `Switch`, `Segmented`, `Meter`, `Confidence`, `AgentIcon` | the controls and indicators |
| `NavRail`, `AppShell` | the sidebar and the page frame |
| `pages/Home`, `Run`, `Compare`, `Browse`, `Agents` | the five example pages |

## Rules for implementing

Add a navigation tab by pushing one item into a group in `lib/nav.ts` and adding its icon path to `icons`; `NavRail` renders from that list, so nothing else changes. The next tab is meant to slot in this way.

Keep state in runes (`$state`, `$derived`) inside the page, and bind controls with `bind:checked` and `bind:value`. `Switch` and `Segmented` are the only controls that hold state, and both keep the hardware behaviour: the switch knob and the segmented thumb animate through `--ease-mech`, which `prefers-reduced-motion` switches off in the CSS.

State is always a word and a glyph. Use `Tag` for process state (live, needs you, queued, done, blocked) and `Verdict` for the decision (recommended, weigh up, avoid); never colour a cell instead. A disputed claim is `Tag state="need"`, and a verdict on a disputed product stays `weigh` until the dispute is settled.

Agent tiles take `src` only from a vendor's official file in `assets/Agents`; without it `AgentIcon` shows the LED monogram.

Do not add a component library or a CSS framework on top. If a pattern is missing (chart, dialog, empty state), build it from glass fills, hairline rows, wells and LEDs as the README says, then add it to `bundle.css` and to this folder together.
