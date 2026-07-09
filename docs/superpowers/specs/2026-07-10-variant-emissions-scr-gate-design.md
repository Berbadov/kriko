# Variant emissions/aftertreatment dimension + SCR serving gate

**Date:** 2026-07-10
**Branch:** `evidence-ledger-stage1`
**Status:** approved design, pre-implementation

## Motivation

Surfaced while reviewing the evidence-ledger claim preview: a K9K AdBlue/DPF claim
(`"DPF and AdBlue failures in K9K diesel"`) grounds to **every** K9K 1.5 dCi variant,
but AdBlue/SCR after-treatment only exists on the **Blue dCi (Euro-6d, SCR-equipped)**
K9K variants — not the earlier Euro-6b (LNT) diesels. The catalog has no emissions
dimension, so "applies to Blue dCi only" cannot be expressed or gated.

The serving plane already scopes claims to compatible variants by fuel, transmission,
and drivetrain (`backend/sync.py` `_fuel_compatible` / `_transmission_compatible` /
`_drivetrain_compatible`). This adds the missing sub-fuel dimension: SCR vs non-SCR
diesel. `_fuel_compatible`'s `_DIESEL_RE` already routes `adblue`/`dpf` claims to
diesel variants; this design adds the finer step below it.

## Scope

**In:** a `Variant` emissions/after-treatment dimension, populated for the current
catalog without hand-editing YAML, and an `_scr_compatible` serving gate.
**Out (YAGNI):** any ledger change — this is pure serving-plane work; and any
euro-standard-based gate beyond SCR (carry `emissions` as data, build only the SCR
gate now). Lands on `evidence-ledger-stage1`.

## §1 — Data model

Two new **nullable** columns on `Variant` (`backend/db/models.py` + `backend/db/schema.sql`):

- `emissions` — Euro standard string, the general fact: `euro5 | euro6b | euro6c |
  euro6d | euro6d_temp` (lowercase, closed vocab). Nullable; absent → unknown.
- `aftertreatment` — closed engineering vocab: `scr | lnt | none`. This is what the
  gate reads. AdBlue ⇔ `scr` is 1:1.

Because Postgres has no migration framework here (schema.sql only auto-applies to a
fresh volume), add both as commented `ALTER TABLE variants ADD COLUMN … ` lines at the
bottom of `schema.sql` (matching the existing convention) for manual application to the
live DB. `backend/tests/conftest.py` already filters YAML rows to `Variant.__table__.columns`,
so extra/absent keys are tolerated.

## §2 — Populating values (no hand-edited YAML)

`aftertreatment` is **derived** from a fixed engineering rule, overridable by data:

```
_default_aftertreatment(fuel, emissions) -> "scr" | "lnt" | "none":
    petrol            -> none
    diesel + euro6d*  -> scr     # SCR/AdBlue is the euro6d-era diesel norm
    diesel + euro6b/c -> lnt
    diesel + <euro6 / unknown -> none
```

This is an allowed closed-vocabulary constant (like the fuel/transmission regexes), not
per-model car data — it does not grow with car coverage.

Per-trim `emissions` **is** data (grows with coverage), sourced like `fuel`/`year_from`
and cross-checked against `catalog.discover`'s Wikipedia data, never hand-typed into YAML:

- **Clio 5, Golf 7** (already in `write_variants.py` `TR_MARKET_TRIMS`): add an
  `emissions` key (and an optional explicit `aftertreatment` override for exceptions) to
  each trim; `build_rows` copies them through.
- **Megane 4** (YAML-only, predates `write_variants.py`): populate via a generic
  procedural script — extend/reuse `knowledge/catalog/backfill_part_field.py` with a
  small **embedded per-trim `id -> emissions` table** (script data, cross-checked vs
  Wikipedia), applied with `--dry-run` then `--apply`. This preserves Megane 4's
  hand-tuned variant rows and keeps it out of hand-edited YAML, rather than retrofitting
  Megane 4 into `write_variants.py` and regenerating (riskier).

`aftertreatment` is computed by `_default_aftertreatment` at generation/backfill time from
each row's `fuel` + `emissions`, then written to the row (with any explicit override
winning), so the served YAML carries a concrete value.

**Data-accuracy checkpoint (implementation):** the specific per-trim `emissions` values
(e.g. which Megane 4 K9K model-years crossed Euro-6b→6d/AdBlue) are real engineering
facts that must be sourced/validated, not guessed — present the proposed `id -> emissions`
table for human sign-off before `--apply`, per the "spot-check automated data against
the source" lesson.

## §3 — The serving gate

`_scr_compatible(claim_data: dict, variant_aftertreatment: str | None) -> bool` in
`backend/sync.py`, mirroring `_fuel_compatible`:

```
_SCR_RE = \b(adblue|ad ?blue|scr|urea|def)\b   # claim explicitly about SCR/AdBlue
def _scr_compatible(claim_data, variant_aftertreatment):
    text = title + " " + rationale (claim's own text, lowercased)
    if not _SCR_RE.search(text):        return True   # no SCR signal -> broad (fail-open)
    if not variant_aftertreatment:      return True   # variant unknown -> broad (fail-open)
    return variant_aftertreatment == "scr"
```

Wired into `sync_parts()`'s per-variant claim-linking loop next to the existing
fuel/transmission/drivetrain checks (~`backend/sync.py:345-349`). Fail-open on either
side missing a signal — same missing-data philosophy as the sibling gates: absence never
excludes.

## §4 — Testing & migration

- `backend/tests/test_transmission_grounding.py` (already covers the sibling gates):
  add cases — an AdBlue claim links to `aftertreatment="scr"` variants; does **not**
  link to a non-SCR (`lnt`/`none`) diesel variant nor a petrol variant; a claim with
  **no** SCR signal still grounds broadly regardless of `aftertreatment`; a variant with
  `aftertreatment=None` grounds broadly.
- Unit test for `_default_aftertreatment` across the fuel×emissions matrix.
- A catalog/data test asserting the K9K Blue dCi Megane 4 variant(s) resolve to
  `aftertreatment="scr"` and the earlier K9K diesel to non-`scr`, proving the AdBlue
  claim now scopes correctly end-to-end.
- `schema.sql` migration note lines, verified applied to the live DB before the final
  `backend.sync`.

## Success criteria

The K9K AdBlue claim links only to SCR-equipped (Blue dCi) Megane 4 variants; non-SCR
K9K diesels and petrol variants no longer receive it; claims without an AdBlue/SCR signal
are unaffected; onboarding a new model needs only trim data (generator/backfill), never a
Python edit to a per-model list.
