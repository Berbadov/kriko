# AEO, GEO and SEO for kriko.cc

Date: 2026-10-30. Branch `feat/aeo-geo`, based on `origin/main` `e1e08056`.

**Done when** a search crawler and an answer engine can both read, from the page
alone: what Kriko is, what it costs, where it runs, the questions a buyer asks,
and the sourced findings behind every product page — with a file at the root
that hands them the map, and a crawler policy that does not shut them out.

## What was already in place

Search was not the gap. `origin/main` already publishes, from
`site/tools/render_problems.py`:

- 676 problem pages — 305 product pages and 31 catalogs, each in English and
  Turkish, plus the two safety hubs — carrying 1,971 sourced reports, each
  linked to the page it came from;
- `BreadcrumbList` on every page, `CollectionPage` with an `ItemList` on the
  category and hub pages, and `Article` with `dateModified` on product pages;
- hreflang pairs, `sitemap-problems.xml` with a `lastmod` per page, and
  `site/tools/indexnow.py` to tell Bing and Yandex when a page changes;
- a 1200×630 share card, and per-page titles that carry the words a buyer uses
  (`Mercedes EQB: known problems and safety risks`).

## What this change adds

1. **Structured data on the hand-written pages** (`site/tools/schema.cjs`, called
   by `render-locales.cjs`). The home page had a visible FAQ and no `FAQPage`;
   the guide had seven sections and no `HowTo`; nothing declared the product.
   The page's own rendered text is the only input, so the Turkish page gets
   Turkish statements and adding a question to the page adds it to the schema.
   A test compares the declared questions and steps with the visible ones.
2. **`site/llms.txt`** (`site/tools/render_llms.cjs`). The plain-text map answer
   engines look for: the one-sentence definition, the platform/price/data facts,
   the main pages, every catalog with its product and report counts, the Turkish
   pages, and how to cite a finding. It is built from the published hub, so a
   catalog that gains or loses pages changes the file; a test fails on a stale
   copy.
3. **`site/robots.txt`** names the search crawlers and the answer engines
   (`GPTBot`, `OAI-SearchBot`, `ChatGPT-User`, `ClaudeBot`, `Claude-SearchBot`,
   `Claude-User`, `PerplexityBot`, `Google-Extended`, `Applebot-Extended`,
   `CCBot`) and allows them everything but `/tools/`, which is not content.
   Wildcard access already implied this; naming them makes the intent explicit
   and survives a future rule added for `*`.
4. **Four answer-shaped questions** on the home page, in English and Turkish:
   which sites it works on, whether there is a Mac or phone app, what a catalog
   is, and whether an AI key is needed. These match the queries people actually
   type before they download.

## Why not more

- **No ratings or review counts.** There are none, and inventing them to earn a
  rich result is a false statement about the product.
- **No hand-written page per product.** The generator is the mechanism: a new
  catalog gets its pages, and the sitemap, `llms.txt`, and hub change with it
  (`CLAUDE.md`, "Generalisation").
- **No `lastmod` on the hand-written pages.** A build date is not the day a page
  was checked, and the generated problem pages already carry a real one.
- **No second copy of the claims in `llms-full.txt`.** The pages already link
  their sources; duplicating 300 pages of text would go stale on every catalog
  release and add nothing a crawler following `llms.txt` cannot reach.

## After the deploy — owner actions, not in this repo

1. Search Console and Bing Webmaster Tools: add the property, submit
   `sitemap.xml` and `sitemap-problems.xml`, and ask for a recrawl of the five
   hand-written pages.
2. `python site/tools/indexnow.py --send` once the deploy is live.
3. Ask an answer engine (Perplexity, ChatGPT search, Bing Copilot) *what is Kriko*
   and *what goes wrong with a Mercedes EQB*, and note whether the answer cites
   `kriko.cc` and links the source.
4. In Cloudflare analytics, watch sessions with a referrer host of
   `chatgpt.com`, `perplexity.ai`, `copilot.microsoft.com`, `gemini.google.com`
   and `bing.com`. That, not a rank position, is the AEO/GEO indicator.

## Verify locally

```sh
npm run build:site
npm run test:site
python -m http.server 4173 --bind 127.0.0.1 --directory site
# then open http://127.0.0.1:4173/llms.txt and view-source on /
```
