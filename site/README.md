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
type is Geist, served from `assets/fonts/` (OFL), so no page loads anything from
another site.

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

The four example products are invented, and so is every finding on them. They are
drawn in the real extension panel: `tools/capture.mjs` runs the extension's own
code in a browser, hands it each product from `tools/examples.json` the way the
engine would, and photographs the panel in light and dark. Nothing on the site
assesses a real manufacturer or model, and each picture says it is an example.

To change an example, edit `tools/examples.json` and then:

```sh
PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs node site/tools/capture.mjs
python3 site/tools/optimise_images.py
```

Playwright and Pillow are only needed for this step; the site itself needs
neither. Commit the new pictures in `assets/examples/`.

## Readability

Body text is 19px with 1.7 line height, lines stay under about 70 characters,
and nothing is set under 15px. The tests check contrast in both themes (7:1 for
body text, 4.5:1 for everything else) and the smallest font size, so a colour or
size change that hurts reading fails the run.
