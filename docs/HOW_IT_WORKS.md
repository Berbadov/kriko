# How Kriko works

Four pictures, one per question people actually ask.

## How does a page find its pack?
```mermaid
flowchart TD
    A["Listing page in the browser"] --> B{"Any adapter<br/>for this host?"}
    B -- no --> B1["<b>no adapter</b><br/>Add the site, or ask an agent to learn it"]
    B -- yes --> C["Adapter reads the page<br/>into key = value pairs"]
    C --> D["Normalise onto the pack's<br/>own vocabulary (aliases)"]
    D --> E{"Exact match on<br/>every identity key?"}
    E -- yes --> F["<b>recognised</b><br/>score 1.0"]
    E -- no --> G["Score every subject:<br/>exact 1.0 · close 0..1 · absent 0<br/>a contradiction counts double against"]
    G --> H{"Best score"}
    H -- "at or above the pack's floor" --> F
    H -- "above the lower band" --> I["<b>probably</b><br/>served, and labelled as a question"]
    H -- below --> J["<b>not recognised</b><br/>names the nearest subject<br/>and which key disagreed"]
```

Floors (`match_floor`, `match_probable` in `gates.yaml`) belong to the pack. No silent nos: `/api/diagnose/identity` returns the full weighing; the panel shows it short.

## Where does a pack come from?
```mermaid
flowchart LR
    A["You name a category"] --> B["Cheap identification pass<br/><i>is this one product or several?</i>"]
    B --> C["Questions, with defaults<br/><i>the run does not wait</i>"]
    C --> D["Research: search, fetch,<br/>extract, ground every quote"]
    D --> E["Draft on disk<br/><i>data only, nothing runs</i>"]
    E --> F{"You read it"}
    F -- "Install it" --> G["In the store,<br/>answering lookups"]
    F -- "Cover the gaps" --> D
    F -- "Throw it away" --> H["Gone"]
```

Agent proposes, Kriko writes (confined dir, fixed names, nothing executable), you install. The identification pass states its assumed scope on the pack instead of blocking.

## What happens during a run?
```mermaid
flowchart LR
    D["<b>Discovery</b><br/>plan the queries<br/>fetch candidates"] --> E["<b>Extraction</b><br/>read each source<br/>quote verbatim"]
    E --> I["<b>Ingestion</b><br/>ground the quote<br/>apply the pack's bar"]
    I --> L["<b>Ledgering</b><br/>write down what was<br/>refused, and why"]
    E -. "cost cap hit" .-> STOP["Stops cleanly.<br/>Everything read is kept."]
    I -. "one field missing" .-> R["Re-ask once,<br/>that field only"]
    R --> I
```

The refusals are the point — without them, keeping nothing looks like keeping everything. Ungrounded quotes are refused, always. Early stops are the cost cap; kept work stays as a partial.

## What is each part of the code?
```mermaid
flowchart TD
    T["<b>tauri/</b> — the desktop shell<br/>owns the sidecar's lifetime, nothing else"] --> U
    U["<b>ui/</b> — the frontend<br/>talks HTTP, knows no pack vocabulary"] --> A
    A["<b>app/</b> — the interfaces<br/>web, CLI, MCP, operator console"] --> K
    P["<b>packs/</b> — one directory per category<br/>data, vocabulary, trust, its own bar"] --> K
    A --> PL["<b>app/pipeline/</b> — pipeline drivers"]
    PL --> PP["<b>packs/cars/pipeline/</b><br/>evidence ledger, grounded extraction"]
    K["<b>kriko/</b> — the engine<br/>imports none of the others<br/><i>knows no category</i>"]
```

The engine importing anything above it is the unforgivable violation (greps in `CLAUDE.md` + an AST test). Packs are consumed through the store, never imported.

## Where things live on disk

| Path | What it is | Survives uninstalling a pack |
|---|---|---|
| `~/.kriko/knowledge.sqlite` | The store — packs, subjects, claims | the pack's rows do not |
| `~/.kriko/app.sqlite` | Your history, settings, saved grids | yes |
| `~/.kriko/models.toml` | What each model costs. Yours to edit | yes |
| `~/.kriko/drafts/` | Agent proposals, before install | yes |

Two databases: uninstalling a pack can't drop history, and history can't change a pack's `content_digest`.

## Next

- [Install it on Windows](INSTALL_WINDOWS.md)
- [Operate it](USAGE.md) — running analyses, growing the knowledge base
- [What a pack must contain](PACK_CONTRACT.md)
- [Mechanism-level reference](INTERNALS.md) — every endpoint and table
