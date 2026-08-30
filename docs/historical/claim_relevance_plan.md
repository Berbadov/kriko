# Plan — Make claim selection match the product principle

Goal: shift served claims from "whatever a blog mentioned" (generic warning lights, fluids,
injector bench tests) to **config- and mileage-specific known risks + due-maintenance items a
buyer can't cheaply get from the standard pre-purchase inspection** (see the principle in
`CLAUDE.md`).

Concretely, for a high-mileage diesel automatic we want to surface things like: *timing belt
due unless the ad shows it was changed*, *dual-clutch/EDC wear expected at this mileage*,
*AdBlue/EGR/DPF grief on this engine* — and we want to STOP surfacing *check brake fluid* /
*ESP warning light* / *injector health* (the ekspertiz covers those).

## Key enabling fact

`ad_metadata` already arrives at `/analyze` with everything we need, scraped by `content.js`
but ignored by the backend today:

- `mileage_km`, `annual_km`, `year` → mileage/age gating
- `description` (full ad text), `equipment`, `damage_info` → "was this maintenance mentioned?"
- `fuel_type`, `transmission`, `engine_volume_cc`, `power_hp` → config

So Phases 1–2 are **backend-only** (no extension changes). The matcher/resolver currently use
only make/model/year/fuel/cc/power/transmission and throw the rest away.

---

## Shared foundation: `ListingContext`

A small dataclass built in `main.py` from `ad_metadata`, threaded into `resolve_claims`:

```python
@dataclass
class ListingContext:
    mileage_km: int | None
    age_years: int | None        # current_year - year
    annual_km: int | None
    fuel_type: str | None
    transmission: str | None
    description: str = ""         # lowercased, for keyword checks
```

`resolve_claims(match, db)` → `resolve_claims(match, db, ctx)`. Built once per request; the
intersection logic for ambiguous matches is unchanged.

---

## Phase 1 — Mileage/age gating (Lever A)  ·  backend only

Let a claim declare when it's relevant, so EDC-wear / DPF-clogging known-issue claims only show
past the mileage where they actually bite.

**Schema (claims YAML, all optional, backward-compatible — omitted = always applies = today's
behaviour):**
```yaml
applies_when:
  min_mileage_km: 120000
  max_mileage_km: null
  min_age_years: 6
```
- New DB columns on `claims` (nullable): `min_mileage_km`, `max_mileage_km`, `min_age_years`.
  `sync.py` loads them; `models.py` adds them.
- `resolver`: drop a claim whose `applies_when` doesn't match `ctx`. **Fail-open**: if the
  listing has no mileage/age, do NOT gate (show it) — never hide a risk because data is missing.

**Deliverable, not just a fixture — author the claim set.** The gating logic gates nothing
without principle-conforming, correctly-thresholded claims, and the blog pipeline won't produce
those. Hand-author ~4 exemplar Megane-4 claims with *real* thresholds as part of this phase
(e.g. EDC clutch wear `min_mileage_km: 120000` on the EDC variants; AdBlue/EGR/DPF clogging on
the diesels). The curated, mileage-tagged claim set IS the product here.

**Validates with:** the EDC-wear seed above — `/analyze` at 190k shows it, at 30k doesn't.

**Tests:** claim shown when mileage ≥ threshold; hidden below; shown when mileage unknown
(fail-open); age gating; existing untagged claims unaffected.

---

## Phase 2 — Maintenance-due claims (Lever B)  ·  backend only · builds on Phase 1

The flagship: "cam belt due unless the ad proves it was changed." A new claim *character* —
predicted-due, not observed-failure.

**Schema** (the `maintenance` block is nested/list-valued → store as a single **JSON column**
on `claims`, not flat columns like `applies_when`):
```yaml
kind: maintenance              # default: known_issue
maintenance:
  interval_km: 90000
  interval_years: 6
  evidence_keywords: ["triger değiş", "kayış değiş", "eksantrik kayışı değiş", "timing belt replaced", "cam belt"]
```
Grounding is per-engine: a **cam-belt** claim must attach only to belt-driven engines. NB our
own data has H5H (1.3 TCe) on a timing **chain**; the diesels (K9K/R9M) are belt — confirm per
engine. Reuse the existing fuel/variant grounding to attach correctly; don't ground a belt
claim to a chain engine.

**Resolver logic for `kind: maintenance`:**
- **Due?** `mileage_km >= interval_km` OR `age_years >= interval_years` (whichever known).
- **Evidence in ad?** any `evidence_keywords` substring in `ctx.description`.
- Due AND no evidence → **show** ("due — the ad doesn't mention a recent change").
- Due AND evidence present → **downrank, do NOT hide** (decision D2, resolved): show a quieter
  "seller states this was done — confirm with a documented service record." Rationale: ad text
  is the seller's unverified claim (the whole premise is *don't trust the ad*), and bare keyword
  matching is dangerous — "triger **sesi geliyor**" (belt *noise*) or "triger **problemli**"
  contains "triger" and would wrongly read as *serviced*. Use change-specific phrases
  (`… değiş*`, `… replaced`) not the bare part name, and still only downrank.
- Not due → hide.
- Mileage/age unknown → fail-open: show as "interval-based — verify service history".

> Recency limitation (known, accept for now): a belt changed once at 90k is due again by 190k,
> but the ad rarely dates the work. We can't reliably extract "changed in the last N years" from
> free text, so "evidence present" only ever *downranks* — never clears — a due item. Good
> enough; date-aware parsing is out of scope.

**Serving/label:** these aren't "confirmed failure" nor "unverified report". Add a third
strength `"due"` → card badge **"Due unless serviced"** (decision D1). API summary counts them
separately ("N maintenance items due").

**Validates with:** a hand-authored cam-belt maintenance claim for Megane 4 diesel; `/analyze`
at 190k with a plain description → shows; with "triger değişti" in description → suppressed.

**Tests:** due+no-evidence shows; due+evidence suppressed; not-due hidden; unknown-mileage
fail-open; keyword match is accent/case tolerant.

---

## Phase 3 — Relevance / "inspection already covers this" filter (Lever C)  ·  offline pipeline

Stop the brake-fluid / ESP-light / injector-bench class from ever being served. Independent of
1–2; affects what the pipeline keeps, not the serving path. Could be done first if killing the
noise is the priority.

- New promote-time gate `gate_inspection_value(claim)` (LLM, offline only): *"Would a standard
  pre-purchase mechanic inspection routinely catch this (fluid levels/leaks, brake-pad wear,
  injector bench test, compression), or is it a generic dashboard warning light true of any
  car? If yes → low value."* Low-value → `rejected` (tombstoned), not served.
- Extend `gate_generic` to also reject pure warning-light claims ("ESP light", "ABS light").
- Optional curated stoplist of low-value title patterns as a cheap pre-filter before the LLM
  call.
- Re-run `--skip-extraction` over the existing cache to re-grade; the brake/ESP/injector-tuning
  claims currently served drop out.

**Tests:** `eval_judge`-style gold cases — belt/EDC/AdBlue kept; brake-fluid/ESP/pads dropped.

---

## Interim (do now, no code) — make the panel look right today

Phases 1–2 add value but do **not** remove the brake-fluid / ESP / injector-tuning cards you
rejected — that's Phase 3. Those claims are already in the YAML as `review`/`held`, so tombstone
them by hand now (`status: rejected`, the documented workflow) and re-sync. The demo is clean
immediately; Phase 3 just makes the filtering systematic so they don't come back.

## Suggested order (one at a time, your call)

1. **Phase 1** first — establishes `ListingContext` plumbing that Phase 2 needs, and immediately
   makes existing known-issue claims mileage-aware. Includes authoring the exemplar claim set.
2. **Phase 2** — delivers the flagship belt/service claims.
3. **Phase 3** — cleans the remaining noise systematically.

Reorder if you'd rather kill the noise first: Phase 3 stands alone.

## Open decisions (pick as we reach them)

- **D1** — Maintenance label: a distinct **"Due unless serviced"** badge (recommended), or fold
  into Confirmed with conditional wording?
- **D2** — *Resolved (advisor):* when the ad mentions the service, **downrank to "confirm with
  a documented record", never hide** — ad text is unverified seller claim and bare keywords
  misfire on negative mentions.
- **D3** — Phase 3 mechanism: LLM gate (more accurate, costs tokens) vs curated stoplist
  (free, brittle) vs both.
- **D4** — Phase order (default above) — kill noise first or build value first?

## Out of scope (for now)

- Cross-run score accumulation, Tier-A ToS-clean sourcing (recall/TSB feeds), and merge
  loosening — tracked elsewhere, not part of relevance.
- Per-variant power/year precision beyond fuel + mileage/age.
