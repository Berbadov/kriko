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
- `404.html`: what an unknown address answers (Cloudflare Pages serves it with a 404
  status). It names its files from the root, because it answers at any depth.
- `robots.txt` and `sitemap.xml`: add a new page to the sitemap, with its Turkish
  twin as an alternate; a test fails when the sitemap and the pages disagree.
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

## The share card

A link to kriko.cc pasted into X, Bluesky, Slack or a chat unfurls into
`assets/share-card.jpg` (1200x630). `tools/share-card.html` lays it out from the site's
own fonts and the hero picture, and `tools/share-card.mjs` photographs it:

```sh
PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs node site/tools/share-card.mjs
```

The home page and the guide name it in `og:image` with its size and a description,
and a test reads the JPEG's own size against those tags. The Turkish pages get their
own address and description from `tr.json` (`og:image:alt`).

## The advertisement

`tools/ad/` draws a 28.5-second advertisement, 1920x1080 at 30 fps, with a
soundtrack, from the same invented e-bike and the pictures above. It is loud on
purpose: thick outlines, a dithered field that moves, a camera that punches on the
beat, 120 BPM. Nothing in it is a recording: `tools/ad/index.html` is one stage,
`tools/ad/scenes.js` sets every element as a function of time (`render(t)`), and
`tools/ad/render.mjs` photographs each frame in a browser and pipes the frames to
ffmpeg. The same time always gives the same frame, so a change is checked by
drawing a few stills before the render.

```sh
PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs node site/tools/ad/render.mjs stills 2.6,13,24.8
python3 site/tools/ad/sheet.py site/tools/ad/out/sheet.png 2.6 13 24.8   # from site/tools/ad
PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs FFMPEG=/path/to/ffmpeg node site/tools/ad/render.mjs video out/kriko-ad-silent.mp4
python3 -I site/tools/ad/score.py                                         # out/kriko-ad.wav
ffmpeg -i out/kriko-ad.wav -af "loudnorm=I=-14:TP=-2:LRA=7,aresample=48000" out/kriko-ad-norm.wav
ffmpeg -i out/kriko-ad-silent.mp4 -i out/kriko-ad-norm.wav -c:v copy -c:a aac -b:a 192k -shortest out/kriko-ad.mp4
ffmpeg -i out/kriko-ad-silent.mp4 -i out/kriko-ad-norm.wav -vf scale=1280:720:flags=lanczos -c:v libx264 -crf 28 -preset slow -pix_fmt yuv420p -c:a aac -b:a 192k -shortest -movflags +faststart ../../assets/film/kriko-ad.mp4
```

`score.py` makes the sound from sine, saw and noise (numpy and scipy), so there is
nothing to license, and it lands its hits on the same times `scenes.js` lands the
pictures. Change one file and change the other. The sound goes through `loudnorm` because
the raw mix peaks above full scale, and a mux limiter alone left a true peak of
+0.8 dBTP after AAC, which clips on some players; this lands at about -14 LUFS with a
true peak near -1.7 dBTP. Keep `-b:a 192k`: at 128k the same mix came out at -0.4 dBTP.
The first mux is the full-size file for a social post (about 54 MB); the last is the
film on the home page, 720p and about 9.5 MB, which has to stay well under the 25 MiB
a Cloudflare Pages file may be (a test keeps it under 12 MB). Cut its still with
`ffmpeg -ss 1.2 -i assets/film/kriko-ad.mp4 -frames:v 1 poster.png` and save it as
`assets/film/kriko-ad-poster.webp`.

The text on screen is the sound-off script, and the three promises are the page's
own lines word for word. `out/` (stills and the videos) is not committed. The ad
says in its corner that the products and findings are invented.

## The problem pages

`problems/` and `tr/problems/` are not written by hand. `tools/render_problems.py`
builds each catalog under `packs/` the way `kriko build` does and writes one page
for every part or product it holds at least three claims about, in each language
the claims are written in, plus a hub that lists them and `sitemap-problems.xml`.
It names no category, so a new catalog or a new car in an old one gets its pages
on the next run.

```sh
PYTHONPATH=src python site/tools/render_problems.py
```

Run it after `render-locales.cjs` whenever a catalog or `styles.css` changes,
because the pages carry the stylesheet's hash. `test_the_pages_in_the_repo_are_what_the_catalogs_say_today`
fails until you do, so a claim the catalog has dropped does not stay on the site.

A page carries a claim's title, body and advice, how it is found, and a link to
each page it was reported on. It never carries the quote the claim was checked
against: that text belongs to its author, and the link sends the reader there.
A catalog that declares itself `synthetic` (the worked example) is never
published, because a made-up claim on a real address is a false statement. The
page text is under the catalog's own licence, which each page names.

### Being found

Each page carries structured data (breadcrumbs and an article for a product, a
collection for a list), a title that names a safety risk when the page reports
one, social tags, and a `lastmod` in the sitemap that is the day the newest
source behind the page was read, so it moves only when the knowledge does.
`problems/safety/` lists every product with a serious fire, explosion or shock
report, and the hub links to it.

After a deploy, once the pages answer on kriko.cc, tell the engines that take
IndexNow (Bing, Yandex and others) what exists. The key file at the root
(`<key>.txt`) is the proof; no account is involved:

```sh
python site/tools/indexnow.py          # what would be sent
python site/tools/indexnow.py --send   # send it
```

Google takes its sitemaps through Search Console, which needs the owner's own
Google account.

### Sponsored placements

`sponsors.json` lists the paid placements, and is empty until there is one. A
placement is `{id, url, name: {en, tr}, text: {en, tr}, catalogs: [slug, ...]}`
(`catalogs` is optional; without it the placement is for every catalog). The
generator shows the first one that fits as a box labelled Sponsored, set apart
by a dashed edge, on a product page and a catalog page, never on the hubs, the
home pages, the guide or the policy, and never inside a finding. It is a plain
link with `rel="sponsored nofollow noopener"`: no script, no cookie, nothing
loaded from the advertiser. A placement whose address is not https, or that has
no words in a page's language, is left out and named on stderr. Add the first
one and the privacy policy already says what it is; a test fails if the policy
stops saying so while any is listed.

## Readability

Body text is 19px with 1.7 line height, lines stay under about 70 characters,
and nothing is set under 15px. The tests check contrast in both themes (7:1 for
body text, 4.5:1 for everything else) and the smallest font size, so a colour or
size change that hurts reading fails the run.
