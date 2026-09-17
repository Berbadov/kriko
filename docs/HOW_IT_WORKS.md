# How Kriko works

Four pictures. Each is the answer to a question people actually ask.

---

## How does a page find its pack?

The one that matters. A reader stands on a listing, and either the panel fills
or it does not — and until 0.10.0 the second case looked identical whether the
pack was missing, the page was misread, or one value was spelled differently.

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

**The thresholds belong to the pack**, not the engine. How near is near enough
is a statement about a product category, and two categories answer it
differently. They ride in `gates.yaml` as `match_floor` and `match_probable`.

**Nothing is ever a silent no.** Every outcome above names what to do next —
that is what `/api/diagnose/identity` returns in full, and what the panel shows
in short.

> **It said "not recognised" and I know the pack covers it.**
> Open the diagnostic. It lists every subject weighed, what the page said, what
> the catalog holds, and which key disagreed. A key reading *conflict* is
> usually the page; a key reading *absent* is usually the adapter.

---

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

Three different authorities, on purpose: **the agent proposes**, **Kriko
writes** (confined directory, fixed filenames, nothing executable), **you
install**. Nothing an agent produces reaches the store without a press.

The identification pass never blocks. It states what it assumed — *"built for
the 2014–2017 1.6 TDI, Turkish market"* — at the top of the pack, because an
assumed scope that is invisible is worse than a wrong one you can see.

---

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

Four stages, and the last one is not an afterthought. **The refusals are the
point**: a run that kept nothing and a run that kept everything produce
identical logs without them.

A quote that does not appear in the page it claims to come from is refused, and
that cannot be negotiated. Everything else is the pack's own bar.

> **My run stopped early.**
> That is the cost cap doing its job. What it had gathered was kept — it is on
> the run as a partial. Raise the cap or pick a smaller scale and run it again.

---

## What is each part of the code?

Dependencies point one way. A package may use what it points at, never the
reverse.

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

**The engine importing anything on this list is the one unforgivable
violation.** The moment it knows what a car is, adding a category stops being a
data change and nobody notices until somebody tries a second one. Four greps in
`CLAUDE.md` enforce it, and a test walks the engine's syntax tree looking for
category vocabulary in executable positions.

A pack is consumed *through the store*, never imported.

---

## Where things live on disk

| Path | What it is | Survives uninstalling a pack |
|---|---|---|
| `~/.kriko/knowledge.sqlite` | The engine's store — packs, subjects, claims | the pack's rows do not |
| `~/.kriko/app.sqlite` | Your history, settings, saved grids | yes |
| `~/.kriko/models.toml` | What each model costs. Yours to edit | yes |
| `~/.kriko/drafts/` | What agents proposed, before you installed it | yes |

Two databases on purpose. Uninstalling a pack must not drop your history, and a
history row must not change a pack's `content_digest`.

---

## Next

- [Install it on Windows](INSTALL_WINDOWS.md)
- [Operate it](USAGE.md) — running analyses, growing the knowledge base
- [What a pack must contain](PACK_CONTRACT.md)
- [Mechanism-level reference](INTERNALS.md) — every endpoint and table
