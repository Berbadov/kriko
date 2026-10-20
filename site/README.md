# Kriko website

Static HTML, CSS and JavaScript. Cloudflare Pages publishes `site/` from `main`
without a build step. Serve the entire directory, including assets and `/tr/`.

```sh
npm ci
npm run serve:site
npm run test:site
```

The English page is `/`; the complete Turkish page is `/tr/`. The header has
explicit EN/TR links. Each page has its own language, metadata, canonical URL
and alternate-language links. Both remain readable without JavaScript. The
shared interaction script localizes product switching, motion controls, menu
labels and announcements using the page's language.

## Editing

- `index.html`: English page and structure.
- `examples.js`: English and Turkish fictional scenarios and sample evidence.
- `locales/tr.json`: Turkish translations of static page text and labels.
- `script.js`: shared interactions and localized control labels.
- `styles.css`: shared responsive layout.

After editing the English page, examples or translations, regenerate both static
fallbacks and the Turkish page, then run the tests:

```sh
node site/tools/render-locales.cjs
npm run test:site
```

The renderer reports missing translations. Commit `tr/index.html` with its
source changes; Cloudflare serves the generated page directly.

## Examples

All four public demonstrations use fictional products, listings and evidence
notes, visibly labeled as such. They assess no real manufacturer or model and
link to no brand-specific failure reports. The illustrations are generic.

- Laptop A: a 256 GB basket compared with a review of the 1 TB configuration.
- Headphones B: a sample crack report, an unknown failure rate and repair checks.
- Espresso machine C: two noise observations with different timing and pressure.
- Hatchback D: dry upper carpet and a water mark in the spare-wheel well.

Each includes an observation, uncertainty and a concrete next check. Sample
notes are displayed in the walkthrough itself. They are not presented as actual
research results, owner reports or catalog findings. Real Kriko research keeps
links to its original sources; this landing page does not run live research.

Product selectors update the illustration, listing, findings and evidence notes
together. Tabs support arrow keys, Home and End. Motion respects reduced-motion
preferences; timed walkthrough playback is opt-in and pauses off-screen or in
background tabs. Tests use jsdom; check the deployed preview visually on desktop
and phone widths as well.
