# How Kriko works

This page explains four things: how a page finds its catalog, how a catalog
grows, what a check does, and where Kriko keeps its files.

## How a page finds its catalog

A page becomes a set of identity keys. An identity key is a pair such as
`make=Toyota`. Kriko never matches on the title of a listing.

1. A site adapter reads the page.
2. Kriko converts the values to the words of the catalog.
3. Kriko compares the keys with every product of the catalog.

The answer has one of four results.

| Result | Meaning |
|---|---|
| **Recognised** | The page and one product agree on every key. Kriko serves the problems of that product. |
| **One of several** | Every key fits more than one product. Kriko serves only what those products share, and it lists them. |
| **Probably** | The nearest product is close, but not exact. Kriko serves its problems and marks the answer as a question. |
| **Not recognised** | No product is close. Kriko names the nearest product and the key that disagrees. |

The catalog holds its own limits (`match_floor` and `match_probable` in its
`gates.yaml`). Kriko does not hide a failure. The route
`POST /api/diagnose/identity` returns the full comparison, and the panel shows
a short form of it.

## How a catalog grows

1. You name a product category.
2. An agent studies the category and proposes a draft.
3. Kriko writes the draft to disk. The draft contains data only.
4. You read the draft, then install it, extend it, or discard it.

An agent cannot put executable code in a draft. Kriko writes every draft file,
and the file names are fixed.

A quick look is also raw material for a catalog. A quick look already carries
its sources and its quotations. When its product is missing from the catalog,
Kriko files the quick look and keeps the sources.

## What a check does

A check has four stages.

| Stage | Work |
|---|---|
| Discovery | Plan the searches and collect the pages. |
| Extraction | Read each page and copy each quotation. |
| Ingestion | Prove each quotation in its page, then apply the bar of the catalog. |
| Ledgering | Write down what Kriko refused, and the reason. |

Kriko refuses a quotation that is not in the page that the agent read. Kriko
refuses a figure with no source. Every refusal names the correction.

The refusals matter. Without them, a check that keeps nothing looks the same as
a check that keeps everything.

A check stops at its cost limit and keeps the work that it finished. A stopped
check is not a failure.

## Where Kriko keeps its files

| Path | Contents | Survives the removal of a catalog |
|---|---|---|
| `~/.kriko/knowledge.sqlite` | The catalogs: products, problems, sources | The rows of that catalog do not |
| `~/.kriko/app.sqlite` | Your history, your settings, and the saved pages | Yes |
| `~/.kriko/models.toml` | The price of each model. You can edit this file. | Yes |
| `~/.kriko/drafts/` | The drafts of agents, before an install | Yes |
| `~/.kriko/env` | The research keys from the Settings screen | Yes |
| `~/.kriko/extension/` | The prepared browser extension | Yes |

Kriko uses two databases on purpose. The removal of a catalog cannot remove
your history, and your history cannot change the digest of a catalog. The
route `/api/health` reports both files.

## Read more

- [Install Kriko on Windows](INSTALL_WINDOWS.md)
- [Use Kriko](USAGE.md)
- [The architecture](ARCHITECTURE.md)
