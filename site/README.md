# Kriko website

Static HTML, CSS and a few lines of JavaScript. Cloudflare Pages publishes
`site/` from `main` without a build step at https://kriko.cc. Serve the whole
directory, including `assets/`, `/tr/` and `/privacy/`.

```sh
npm ci
npm run serve:site
npm run test:site
```

The page is white by default and follows the visitor's system for dark. Every
colour is a token at the top of `styles.css`; the dark theme is one block. The
look is Kriko's own and is kept on purpose, not left to defaults:

- **Headings** are Barlow Condensed, which is the wordmark's own proportion.
- **Body text** is Atkinson Hyperlegible Next, a face drawn for reading.
- **The sky** is the app's dithered pixel sky, drawn by `tools/dither_sky.py` with
  the app's own method and palette, in a light and a dark version.
- **The paper** is a warm white, with the product's blue used only for actions,
  numbers and links.

Both typefaces are served from `assets/fonts/` (OFL), so no page loads anything
from another site.

## Editing

- `index.html`: the English page and its structure. It is the source of the
  Turkish page.
- `locales/tr.json`: the Turkish text. Each key is a unit of text exactly as it is
  written in the English page, including any `<strong>` or `<a>` inside it. A
  sentence is translated whole, never in pieces. The app's own menu names stay
  English in both languages, because the app is English.
- `guide/index.html`: how to use Kriko, one short film per step. Also a source of
  a Turkish page; see below.
- `privacy/index.html`: the privacy policy. English only.
- `styles.css`, `script.js`: shared by every page. `script.js` runs the menu on a
  narrow screen and puts a pause button on each film in the guide.

After editing the English page, the stylesheet, the script or the translations:

```sh
node site/tools/render-locales.cjs
npm run test:site
```

The renderer writes `tr/index.html` and `tr/guide/index.html`, puts a content hash
on the stylesheet and script of every page, and fails with the list of texts that
have no translation. A test fails if either Turkish page is stale. To give another
page a Turkish version, add it to `PAGES` in `render-locales.cjs` and give it an
`@meta:<name>` entry in `tr.json`. In a Turkish page a link to `/`, `/#place` or
`/guide/` is sent to the Turkish version, and `/privacy/` stays English.

## The guide

`guide/index.html` walks through using Kriko with a film of each step: check a
listing, research something new, find a saved check, compare, and choose how much
doubt to see. The films are GIFs in `assets/guide/`, each with a poster still
(`<name>-poster.webp`). A film plays by itself and has a Pause button; a reader who
has asked for less motion gets the still first, through a `<source>` in the
`<picture>`, so that works without script. Every product in them is invented.

`tools/capture-guide.mjs` records the films with the real apps. A scene is a short
script of mouse moves and presses; Playwright films the page, with a pointer drawn
into it because a recording shows no mouse, and ffmpeg cuts the part that matters.
The extension's panel is the real panel (`tools/panel-harness.mjs`, shared with
`capture.mjs`) and the desktop window is the real window on a real engine
(`tools/app-harness.mjs`, shared with `capture-app.mjs`), both on the same invented
data as the pictures below.

```sh
npm ci --prefix kriko-ui && npm run build --prefix kriko-ui
PYTHON=/full/path/to/python PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs FFMPEG=/path/to/ffmpeg node site/tools/capture-guide.mjs
```

`ONLY=compare,doubt` records some of the scenes. A test keeps each GIF under 2.5 MB;
a new scene needs its entry in `guide/index.html` and in `locales/tr.json`.

## Examples

Every example product is invented, and so is every finding on them. They are
drawn in the real extension panel: `tools/capture.mjs` runs the extension's own
code in a browser, hands it each product from `tools/examples.json` the way the
engine would, and photographs the panel in light and dark. Nothing on the site
assesses a real manufacturer or model, and each picture says it is an example.

`examples.json` holds three kinds of entry. `products` are the panels the page
shows (the e-bike is the one the hero and the three steps follow, the other four
fill the gallery), `research` is the one product no catalog knows, and
`shortlist` is what sits beside the e-bike in the Compare picture. A new product
under `products` needs its two pictures, which the capture writes and a test
checks. The panel's theme is the reader's stored choice, so the capture names
it for each picture; a new panel state that asks the worker for something the
preview page does not answer needs a stub in `capture.mjs`.

To change an example, edit `tools/examples.json` and then:

```sh
PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs node site/tools/capture.mjs
python3 site/tools/optimise_images.py
```

Playwright and Pillow are only needed for this step; the site itself needs
neither. Commit the new pictures in `assets/examples/`. The sky pictures are made
the same way (`python3 site/tools/dither_sky.py`) and live in `assets/sky/`.

## The desktop app's pictures

The pictures in the app section are the real desktop interface too.
`tools/capture-app.mjs` starts a real engine in an empty home folder of its own,
fills its saved checks, queue and comparison with the invented e-bikes
(`tools/seed_app_examples.py`, from `examples.json` and `app_examples.json`),
opens the built window (`kriko-ui/dist`) on it and photographs three screens.
Nothing of the machine it runs on reaches a picture: the engine's home is a
temporary folder, its extension port is off, and the agents it lists are not
read from this machine's PATH when `PYTHON` is a full path. The two provider
keys it holds are placeholders, so the window offers the Kriko Agent; nothing
runs a search.

The sources carry the `tier` a catalog would give them, and the Solid, Partial
and Thin marks on each finding are the engine's own grading of them
(`app/evidence.py`), not a label written for the picture.

```sh
npm ci --prefix kriko-ui && npm run build --prefix kriko-ui
PYTHON=/full/path/to/python PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs node site/tools/capture-app.mjs
python3 site/tools/optimise_images.py
```

Commit the pictures in `assets/desktop/`. The comparison is drawn wide, for a
desktop screen, and narrow, for a phone. The checked product and the start
screen are only shown narrow, so they are drawn only at that size. `ONLY=compare`
draws one picture.

## Readability

Body text is 19px with 1.7 line height, lines stay under about 70 characters,
and nothing is set under 15px. The tests check contrast in both themes (7:1 for
body text, 4.5:1 for everything else) and the smallest font size, so a colour or
size change that hurts reading fails the run.
