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
- `privacy/index.html`: the privacy policy. English only.
- `styles.css`, `script.js`: shared by every page. `script.js` only runs the menu
  on a narrow screen.

After editing the English page, the stylesheet, the script or the translations:

```sh
node site/tools/render-locales.cjs
npm run test:site
```

The renderer writes `tr/index.html`, puts a content hash on the stylesheet and
script of every page, and fails with the list of texts that have no translation.
A test fails if `tr/index.html` is stale.

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

## Readability

Body text is 19px with 1.7 line height, lines stay under about 70 characters,
and nothing is set under 15px. The tests check contrast in both themes (7:1 for
body text, 4.5:1 for everything else) and the smallest font size, so a colour or
size change that hurts reading fails the run.
