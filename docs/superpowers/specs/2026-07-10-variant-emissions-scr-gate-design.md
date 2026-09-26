> TL;DR (archived 2026-09-25): Design (2026-07-10, approved) adding the missing emissions
dimension: nullable `emissions` (Euro string) + `aftertreatment` (`scr|lnt|none`, derived by
fixed rule) on `Variant`, populated without hand-edited YAML, plus a fail-open
`_scr_compatible` serving gate so AdBlue/SCR claims reach only SCR (Blue dCi) diesels.

# Variant emissions/aftertreatment dimension + SCR serving gate

**Date:** 2026-07-10 · **Branch:** `evidence-ledger-stage1` · **Status:** approved design, pre-implementation

## Motivation

K9K AdBlue/DPF claim grounds to **every** K9K 1.5 dCi variant — but AdBlue/SCR exists only on **Blue dCi (Euro-6d)** K9Ks, not Euro-6b (LNT). The catalog has no emissions dimension, so "Blue dCi only" is inexpressible. Serving already scopes by fuel/transmission/drivetrain (`_fuel_compatible` etc. in `backend/sync.py`); this adds the sub-fuel step (SCR vs non-SCR diesel).

## Scope

**In:** `Variant` emissions dimension populated without hand-editing YAML + `_scr_compatible` gate. **Out (YAGNI):** ledger changes (pure serving-plane); any euro-standard gate beyond SCR (carry `emissions` as data, build SCR only). Lands on `evidence-ledger-stage1`.

## §1 — Data model

Two **nullable** columns (`backend/db/models.py` + `schema.sql`): `emissions` (`euro5|euro6b|euro6c|euro6d|euro6d_temp`, absent = unknown); `aftertreatment` (`scr|lnt|none` — what the gate reads; AdBlue ⇔ `scr` 1:1). No migration framework (fresh-volume auto-apply only) ⇒ add commented `ALTER TABLE ... ADD COLUMN` lines at `schema.sql` bottom per convention for the live DB. `conftest.py` already tolerates extra/absent keys.

## §2 — Populating values (no hand-edited YAML)

`aftertreatment` **derived** from a fixed rule (closed-vocab constant like the fuel regexes, not per-model data), overridable: petrol→none; diesel+euro6d*→scr; diesel+euro6b/c→lnt; diesel+older/unknown→none. `emissions` **is** data (grows with coverage), sourced like fuel/year and cross-checked vs `catalog.discover` Wikipedia data, never hand-typed: **Clio 5, Golf 7** (in `write_variants.py` `TR_MARKET_TRIMS`) gain an `emissions` key (+ optional `aftertreatment` override) copied through `build_rows`; **Megane 4** (YAML-only) via procedural backfill — extend `backfill_part_field.py` with an embedded per-trim `id → emissions` table, `--dry-run` then `--apply` (preserves hand-tuned rows; no risky `write_variants.py` retrofit). Rows carry concrete `aftertreatment` (rule output, override wins). **Accuracy checkpoint:** per-trim values (which K9K years crossed 6b→6d/AdBlue) are engineering facts — human sign-off on the table before `--apply` ("spot-check automated data").

## §3 — The serving gate

`_scr_compatible(claim_data, variant_aftertreatment) -> bool` in `backend/sync.py`, mirroring `_fuel_compatible`: regex `\b(adblue|ad ?blue|scr|urea|def)\b` over claim title+rationale; no SCR signal ⇒ True; unknown variant ⇒ True; else `== "scr"`. Wired into `sync_parts()` linking loop (~`sync.py:345-349`). Fail-open on missing signal either side (absence never excludes — sibling-gate philosophy).

## §4 — Testing & migration

Extend `test_transmission_grounding.py`: AdBlue claim links to `scr`, not to `lnt`/`none` diesel nor petrol; SCR-signal-free claims ground broadly; `aftertreatment=None` grounds broadly. Unit-test the fuel×emissions matrix; catalog test proving Blue-dCi K9K ⇒ `scr`, earlier K9K ⇒ non-`scr`. Apply `schema.sql` migration lines to live DB before final `backend.sync`.

## Success criteria

K9K AdBlue claim links only to SCR (Blue dCi) Megane 4s; non-SCR diesels + petrols excluded; signal-free claims unaffected; new models need only trim data, never a per-model Python edit.
