# How Kriko works

Four pictures, one per question people actually ask.

## How does a page find its catalog?

```mermaid
flowchart TD
    A["A listing page in the browser"] --> B{"An adapter<br/>for this host?"}
    B -- no --> B1["<b>no adapter</b><br/>Teach the site, or ask an agent to learn it"]
    B -- yes --> C["The adapter reads the page<br/>into key = value pairs"]
    C --> D["Normalise onto the catalog's<br/>own vocabulary"]
    D --> E{"Exact match on<br/>every identity key?"}
    E -- yes --> F["<b>recognised</b><br/>score 1.0"]
    E -- no --> G["Score every subject:<br/>exact 1.0, close 0 to 1, absent 0<br/>a contradiction counts double against"]
    G --> H{"Best score"}
    H -- "at or above the pack's floor" --> F
    H -- "above the lower band" --> I["<b>probably</b><br/>served, and labelled as a question"]
    H -- below --> J["<b>not recognised</b><br/>names the nearest subject<br/>and which key disagreed"]
```

The floors (`match_floor`, `match_probable` in the pack's `gates.yaml`) belong
to the pack. There is no silent no: `POST /api/diagnose/identity` returns the
whole weighing, and the panel shows a short form of it.

## Where does a catalog come from?

```mermaid
flowchart LR
    A["You name a category"] --> B["Cheap identification pass<br/><i>one product, or several?</i>"]
    B --> C["Questions, each with a default<br/><i>the run does not wait</i>"]
    C --> D["Research: search, fetch,<br/>extract, ground every quote"]
    D --> E["Draft on disk<br/><i>data only, nothing runs</i>"]
    E --> F{"You read it"}
    F -- "Install it" --> G["In the store,<br/>answering checks"]
    F -- "Research the gaps" --> D
    F -- "Discard it" --> H["Gone"]
```

The agent proposes and Kriko writes: a confined directory, fixed file names,
nothing executable. The identification pass states the scope it assumed on the
pack itself rather than stopping to ask, so an assumption is visible instead of
invisible.

## What happens during a run?

```mermaid
flowchart LR
    D["<b>Discovery</b><br/>plan the queries,<br/>fetch candidates"] --> E["<b>Extraction</b><br/>read each source,<br/>quote verbatim"]
    E --> I["<b>Ingestion</b><br/>ground the quote,<br/>apply the pack's bar"]
    I --> L["<b>Ledgering</b><br/>write down what was<br/>refused, and why"]
    E -. "cost cap hit" .-> STOP["Stops cleanly.<br/>Everything read is kept."]
    I -. "one field missing" .-> R["Re-ask once,<br/>that field only"]
    R --> I
```

The refusals are the point: without them, keeping nothing looks like keeping
everything. An ungrounded quote is refused, always. An early stop is the cost
cap, and the work already done stays as a partial rather than dying with the
request.

## What is each part of the code?

```mermaid
flowchart TD
    T["<b>tauri/</b> — the desktop shell<br/>owns the sidecar's lifetime, nothing else"] --> U
    U["<b>ui/</b> — the frontend<br/>talks HTTP, knows no catalog's vocabulary"] --> A
    A["<b>app/</b> — the interfaces<br/>web, CLI, MCP, operator console"] --> K
    P["<b>packs/</b> — one directory per category<br/>data, vocabulary, trust, its own bar"] --> K
    A --> PL["<b>app/pipeline/</b> — pipeline drivers"]
    PL --> PP["<b>packs/<name>/pipeline/</b><br/>evidence ledger, grounded extraction"]
    K["<b>kriko/</b> — the engine<br/>imports none of the others<br/><i>knows no category</i>"]
```

The engine importing anything above it is the unforgivable violation: the greps
are in `CLAUDE.md` and an AST test holds them. A pack is consumed through the
store, never imported.

## Where things live on disk

| Path | What it is | Survives uninstalling a pack |
|---|---|---|
| `~/.kriko/knowledge.sqlite` | The store: packs, subjects, claims | the pack's rows do not |
| `~/.kriko/app.sqlite` | History, settings, saved comparisons | yes |
| `~/.kriko/models.toml` | What each model costs. Yours to edit, copied once and never rewritten | yes |
| `~/.kriko/drafts/` | Agent proposals, before install | yes |
| `~/.kriko/env` | Research keys, written by the app's Settings screen | yes |

Two databases, on purpose: uninstalling a pack cannot drop history, and history
cannot change a pack's `content_digest`.

## Next

- [Install it on Windows](INSTALL_WINDOWS.md)
- [Operate it](USAGE.md), including growing the knowledge base
- [What a pack must contain](PACK_CONTRACT.md)
- [Mechanism-level reference](INTERNALS.md), every endpoint and every table
