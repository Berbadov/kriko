# Category packs: a product check lands in the knowledge store

*2026-09-29. Backlog **B168**, **B169**, **B170**. The reader's words: "Singular product searches must be addable to the DB", "Singular product searches must not create a new pack each time", "Singular product searches must be turned into packages", "Revise the engine flow for the above".*

## What was wrong

- A quick look on an unknown product produced sourced risks that lived only in `app.sqlite` `jobs.result_json`. Nothing ingested them, so `/api/search` never found the product.
- The deepen job (`pack_author` with `product_only`) authored one whole pack per listing title. Eight such packs exist on the reader's machine, most with one subject, one of them named from a Turkish title.
- Checking the same product again met an existing draft directory and failed with `FileExistsError`.
- `packstore.install` refuses a changed digest at an unchanged version, and nothing ever changed the version, so an amended draft could not be installed again.

## The flow

```
extension door -> quick_look (quick lane)          -> risks, category, pack choice
               -> pack_author, product mode (main lane)
                    1. wait for the quick look (bounded)
                    2. resolve a category pack, or author one
                    3. put the product in it, with the quick look's risks as sourced claims
                    4. bump the version, rebuild the .kpack, install
```

### 1. The category comes from data

The engine never lists categories. A category pack is an ordinary installed pack that was authored from a draft (a draft directory whose `.installed` marker names the pack). Cars and drill have no draft, so they are never a target (B170, "Not this").

The quick look receives a block built from those packs: id, name, identity keys, a few subject labels and the first lines of the pack's own principle. It answers two extra fields:

- `pack`: the id of a listed pack this product belongs in, or empty.
- `category`: what kind of product this is, in two to four words, with no brand or model.

`app/categorypack.py` validates the answer against the installed list. An id that is not in the list is ignored. When `pack` is empty it falls back to comparing the `category` words with each candidate's name, and it only accepts one clear winner. Anything unclear resolves to "no pack": a new category pack is authored. Nothing here waits for a person and nothing here is a typed list.

### 2. Two paths, one result

- **A pack fits.** The deepen job asks the agent for the product as one subject that uses the pack's own identity keys (the existing amend brief, with a product note). A repeat of a product already in the pack returns the same identity, which is a normal outcome rather than a refusal.
- **No pack fits.** The deepen job authors a new pack named for the category, with the product as its first subject. The brief lists the ids already taken. The rest of the category goes in `lineup` as open gaps, not as research. If the agent still picks an id that has a draft, the reply is merged into that draft instead of failing.

### 3. Sourced claims only

The quick look's risks become claims on the product subject. Each carries `evidence` (url, quote). A quote is checked again against the page text: the text the quick look kept when its plane retained it, otherwise a fetch through `app/providers/fetch.py`. A quote that is not in the page is dropped and logged, never kept without a source. The same rule applies to any claim the deepen agent proposes: claims without grounded evidence are dropped in product mode. The pack's own gate rows (`kriko.gates`) are applied as `accept_findings` applies them, and are empty for an authored pack.

Claim rows carry the confidence `accept_findings` gives agent claims, so ranking treats both doors alike.

### 4. The pack grows as a package

Installing a draft goes through one function, `categorypack.install_draft`. It builds the draft, compares its digest with the installed one, and when the content changed at an unchanged version it raises the patch number in the draft's `pack.toml` and builds again. `packstore.install` is untouched: the rule that a version is immutable stays, and the author stops republishing it.

Store-only claims (accepted by a research run on this pack) would be dropped by a reinstall, which replaces the pack's rows. Before a rebuild the draft absorbs them: claims in the installed pack that the draft does not hold are written back into `data/claims.yaml` with their evidence, so the draft stays the complete record and the exported `.kpack` carries them.

Because one product check now reinstalls a category pack each time, the exported `.kpack` beside the draft is the same file another machine installs.

## What does not change

- `kriko/` learns nothing. The engine sees ordinary packs, and the version bump lives in `app/`.
- Existing per-product packs on a machine stay as they are. B188's reset removes them.
- The extension is untouched. The deepen job is still a `pack_author` job and still ends with `installed: true`, which is what makes the panel look the listing up again.
- The first-party packs in `packs/` are not editable from the app.

## Failure behaviour (fail open)

| Situation | Result |
|---|---|
| The quick look failed or found no sourced risks | The product still joins a pack, with no claims. |
| No page can be read for a quote | That claim is dropped and named in the job log. |
| The agent's reply is not a pack | The job fails with the reason, as before. Nothing is installed. |
| Install is refused (for example a downgrade) | The draft is kept and the log says why. |
| The quick look never appears or is slow | The deepen job waits a bounded time, then carries on without its answer. |

## Tests

Journeys through the door with the agent and the page reader stubbed: V8 then V6 leaves one pack with two subjects; the same product twice succeeds; a quote that is not on the page is dropped; version and digest advance on each join; `/api/search` finds the product and the claim shows its source; the exported `.kpack` installs into an empty store with the product in it; a research finding accepted before a join survives the reinstall.
