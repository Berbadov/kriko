# The pack contract

A pack is a directory under `packs/`. This is the whole contract: what
`src/kriko/pack/manifest.py` enforces when it loads one, plus the parts a pack
grows into once it needs more than the minimum. It is written for someone who
has never seen this repo and wants to ship a pack for a product category
nobody has thought about yet.

Enforcement lives in one place: `src/kriko/tests/test_pack_contract.py`. It loads
every pack under `packs/` and checks each against the rules below, plus a
guard that the repo ships more than one pack — a contract validated against a
single example proves nothing. If your pack fails that test, fix your pack,
not the test.

## The required minimum

1. **`pack.toml`** at the pack's root, with a `[pack]` table declaring:
   - `id` — a stable identifier (e.g. `org.kriko.drill`).
   - `name` — a human-readable name.
   - `version` — a version string.

   `publisher`, `license`, and `origin` are read if present but are not
   enforced.

2. **A non-empty `[identity]` table.** It maps each subject kind your pack
   deals in (e.g. `product`, `part`, `battery_platform`) to the list of
   attribute keys that make a subject of that kind distinct. Every kind you
   declare must map to at least one key — an empty list is as invalid as a
   missing table.

3. **A `data/` directory** containing at least one `*.yaml` file (searched
   recursively). A pack with no rows is not a pack — it is an announcement.

4. **A `README.md`** at the pack's root. A pack is a thing someone installs;
   it must say, in prose, what it covers.

Nothing else is required. `packs/drill/` — five YAML files and a README — is
already at this floor and passes the contract test exactly as it is.

## Why `[identity]` is the most consequential declaration

`[identity]` is not bookkeeping — it decides what counts as "the same
product". Two packs that both describe, say, cordless drills will only have
their rows merge at lookup time if they hash a given drill to the same
identity. Get the attribute set wrong (too narrow, and unrelated products
collide into one subject; too specific, and the same real-world product ends
up split across several subjects that never see each other's claims) and the
result is silent — not a crash, just claims that never combine, or claims
that combine when they shouldn't. As `src/kriko/pack/manifest.py` puts it in the
error it raises when `[identity]` is empty: without declared identity keys,
"every subject of a kind would hash to the same id."

There is no single correct shape. `packs/cars/pack.toml` hashes a `product`
on seven keys (make, model, engine code, fuel, displacement, transmission
code, minimum power) because two cars that differ in any of those are not
interchangeable for the claims this pack makes. `packs/drill/pack.toml`
hashes its `product` kind on two keys (`brand`, `model`) and gives a
`battery_platform` kind its own single-key identity — a shape a car-shaped
schema could not express at all. A different author modelling the same
category with a different identity table is not wrong; their rows simply
won't collapse with yours. They'll still union at lookup by attribute
overlap (see `src/kriko/tests/test_lookup.py`'s cross-pack union tests) — which
is the intended failure mode, not a bug to fix.

## The optional parts

None of these are enforced by the contract test. Each buys you something a
mature pack needs; a pack that doesn't need it doesn't carry it.

- **`vocabulary/`** — gate terms and adapter vocabulary the engine's generic
  ranking/gating logic reads as pack-declared rows instead of hardcoded
  Python. Present in both `packs/drill/vocabulary/` and
  `packs/cars/vocabulary/`.
- **`research/`** — everything an agent needs to research *this* category,
  and the three files are read by name:
  - `principle.md` — what is worth surfacing for this kind of product, and what
    a reader could get more cheaply elsewhere. It is quoted verbatim into every
    research brief and into the generated agent skill, so it is the pack's own
    bar rather than the engine's.
  - `templates.yaml` — the searches to run, one query per line, with `{label}`,
    `{alias}` and any of the pack's identity keys substituted in. **Effectively
    required.** A pack that omits it renders *zero* queries, and its brief then
    says what to keep without ever saying what to look for — which is what a
    reader experiences as a Research button that does nothing. `kriko pack
    scaffold` writes a starting set derived from the identity keys declared.
  - `skill.md` — optional: how to resolve a subject's *identity* before
    searching for it, since "the make and model" is a guess and the
    discriminating attribute is a method. Where present it becomes a section of
    the generated agent skill.

  `kriko/pack/build.py` is the list that decides which of these ship; a file
  not named there is not carried into the `.kpack`. Present in both
  `packs/drill/research/` and `packs/cars/research/`.
- **`trust/`** — source trust tiers, for a pack whose pipeline ingests from
  sources of varying reliability. Present in `packs/cars/trust/`; drill has
  none — its data is synthetic, so there's nothing to weigh.
- **`adapters/`** — site-specific scraping/extraction rules, for a pack whose
  pipeline reads live listings from named sites. Present in
  `packs/cars/adapters/`; drill has none. An adapter maps the page's own
  labels onto identity and context keys (`identity`, `context`, `derive`,
  `ignore_labels`), and may also declare a **`local_panel`**: the selectors,
  the site's own words, the English titles and hints, and the alert thresholds
  for blocks the client renders from the page itself rather than from the
  engine's answer — the cars pack uses it for a body-damage silhouette and an
  equipment list. `GET /api/adapters` hands it to the client verbatim; the
  engine never inspects it, and an adapter that declares none gets `{}`.

  **All of it is data, and that is a security boundary.** A pack may not ship
  JavaScript, a regex, or any other executable string, here or anywhere:
  installing a pack would then mean granting its author the ability to run
  code on every page the client can see. The format is a fixed vocabulary of
  term lists, selectors and numbers, interpreted by `kriko/adapters.py` and by
  the extension. Anything it cannot express is a reason to extend those two —
  in review, once — never to open that door.
- **`build.py`** — a custom builder, when the engine's generic build step
  isn't enough to turn a pack's data into an installable artifact. Present as
  `packs/cars/build.py`; drill relies on the generic path.
- **`pipeline/`** — the category's own evidence pipeline: whatever turns raw
  sources into the claims the pack ships. This is the part that scales with
  category maturity — `packs/cars/pipeline/` is the bulk of that pack's
  ~12,900 lines. Drill has none; its claims are hand-authored and synthetic
  by design.
- **`coverage.py`** — a category-specific coverage report, surfacing what the
  pack's data is missing. Present as `packs/cars/coverage.py`; drill has none.

## Start here

Copy `packs/drill/` as the minimum viable pack. Read `packs/cars/` to see what
a mature pack grows into once it has a real pipeline, real sources, and real
scale behind it. Nothing in between those two shapes is required — only the
four items in "The required minimum" are.

## Enforcement

`src/kriko/tests/test_pack_contract.py` is the authority. It is parametrized over
every pack the repo ships and checks each against the required minimum above,
plus a guard that the repo ships more than one pack. If this document and
that test ever disagree, the test is right and this document needs fixing.
