# Kriko — System Overhaul Plan

The umbrella roadmap for turning Kriko from "extracts whatever a blog mentioned" into a tool
that surfaces **the config- and mileage-specific risks a buyer can't cheaply get from the
standard pre-purchase inspection** (the principle — see `CLAUDE.md`).

This is the strategic map. Phase-level mechanics for claim relevance live in
`docs/claim_relevance_plan.md`; this doc places them in the larger picture and adds the
sourcing, serving, and scaling layers.

---

## 0. The core reframing

Two beliefs drive the whole overhaul:

1. **The valuable claims are curated domain knowledge, not scraped text.** "Cam belt due by X
   km", "EDC clutch wears past Y km", "this engine's AdBlue/EGR/DPF clogs" — these are authored
   by someone who knows the car, with real thresholds. The blog pipeline is a *lead generator*
   (what to investigate), not the source of truth.
2. **Relevance is a function of the listing, not just the variant.** Mileage, age, and the ad's
   own text decide whether a claim matters. The backend already receives all of this
   (`mileage_km`, `annual_km`, `description`, `equipment`, `damage_info`) and throws it away.

Everything below follows from these two.

---

## 1. Current state (honest snapshot)

**Done this cycle:**
- Serving widened past `verified` to labelled `Confirmed` / `Reported` strengths; summary never
  asserts an unverified report as fact; `has_source` keeps ungrounded noise out.
- Fuel-aware grounding (diesel claims don't show on petrol).
- `sync.py` prunes claims removed from YAML (was upsert-only).
- Pipeline unblocked (zstd fetch, truncated-JSON salvage, gates judge source text).
- Manual cleanup: the brake-fluid / ESP / injector-tuning noise tombstoned.

**Not yet true:**
- Nothing is mileage/age aware — a claim shows the same at 30k and 300k.
- No maintenance-due concept ("belt due unless the ad shows it").
- Relevance isn't enforced systematically — noise returns on the next pipeline run.
- High-value claims are thin: only a handful of hand-authored seeds exist.
- Sourcing leans on ToS-restricted blogs; no authoritative (recall/TSB) feed.

---

## 2. Target system ("done" looks like)

A buyer opens a listing; the panel shows, ranked by what matters for *this* car at *this*
mileage:

- **Confirmed known issues** for the engine/gearbox (corroborated or expert-authored).
- **Due maintenance** flagged against the odometer, "unless the ad/service record proves
  otherwise."
- Nothing the ekspertiz routinely catches (fluids, pads, injector bench, warning lights).

Powered by:
- A **context-aware resolver** that filters/ranks claims using a `ListingContext`.
- A **claim model (v2)** rich enough to express config + mileage + maintenance + relevance.
- A **curated-first claim set**, with authoritative feeds and the blog pipeline demoted to leads.

---

## 3. The claim model (schema v2) — the spine of the overhaul

One backward-compatible schema that every phase extends. All new fields optional; omitted =
today's behaviour.

```yaml
# identity / content (existing)
id, claim_key, title, domain, severity, confidence, rationale, inspection_advice,
status, promoted_by, variants[], sources[]

kind: known_issue | maintenance | recall      # default known_issue

applies_when:                                  # Phase 1 — flat, nullable columns
  min_mileage_km: 120000
  max_mileage_km: null
  min_age_years: 6

maintenance:                                   # Phase 2 — JSON column (nested/list)
  interval_km: 90000
  interval_years: 6
  evidence_keywords: ["… değiş*", "… replaced"] # change-specific, never bare part name

value_tier: core | routine_inspection | generic_warning   # Phase 3 — relevance
# core = what we exist to show; routine_inspection / generic_warning = dropped/downranked
```

DB: add nullable columns for `kind`, `applies_when.*`, `value_tier`; a JSON column for
`maintenance`. `sync.py` loads them; `models.py` declares them; resolver consumes them.

---

## 4. Roadmap (phases — one at a time)

### Phase 0 — Manual cleanup ✅ done
Tombstoned the inspection-covered / generic-warning noise so the panel reads right today.

### Phase 1 — Context plumbing + mileage/age gating + first authored claims
`ListingContext` from `ad_metadata`, threaded into `resolve_claims`; `applies_when` gating,
fail-open on missing data; author ~4 real mileage-tagged Megane-4 claims.
→ details in `docs/claim_relevance_plan.md` (Phase 1).

### Phase 2 — Maintenance-due claims
`kind: maintenance`, interval logic, ad-evidence **downranks (never hides)**, "Due unless
serviced" label, per-engine belt-vs-chain grounding.
→ details in `docs/claim_relevance_plan.md` (Phase 2).

### Phase 3 — Relevance filter (systematic)
Offline `gate_inspection_value` + extended `gate_generic`; sets `value_tier`; drops the noise at
the source so it never returns. Re-grade existing cache with `--skip-extraction`.
→ details in `docs/claim_relevance_plan.md` (Phase 3).

### Phase 4 — Sourcing overhaul (curated-first + authoritative feeds)
- Make **hand-authoring** a first-class, documented workflow (a per-model authoring checklist
  derived from the principle: belt/chain, clutch type, emissions hardware, known weak points,
  mileage thresholds).
- Add a **ToS-clean authoritative tier**: official recall / technical-service-bulletin data
  (EU Safety Gate/RAPEX, KBA, NHTSA for shared engines) as `kind: recall`, high trust, publicly
  published — the real substitute for ToS-restricted specialist (Tier A) blogs.
- Demote the blog pipeline to a **lead generator**: it proposes issues to investigate/author.
  **Contingent on D6** — this pulls against the `Reported` tier you asked for earlier ("signal
  the general idea, at worst"), which auto-serves blog `review`/`held` claims today. Resolve D6
  before acting on this bullet.

### Phase 5 — Serving / UX polish
- Rank: Confirmed core → Due maintenance → Reported. Mileage/age shown as the "why this".
- "Due unless serviced" badge; suppress numeric confidence on non-confirmed cards (done).
- Fix summary wording so it only mentions report/maintenance buckets that are non-empty
  (current nit: "unverified reports are…" prints even when zero reports).
- Distinguish the coverage states the UI currently flattens (MATCHED_NO_DATA vs 0 risks).

### Phase 6 — Scale to new models
With schema v2 + the authoring checklist, onboard a second model end-to-end to prove the
process generalises beyond Megane 4.

---

## 5. Cross-cutting / deferred (not blocking the phases)

- **Cross-run corroboration accumulation** — a held claim upgrading when a new independent
  source appears in a later run (today each run is independent).
- **Merge loosening** (turbo≈turbocharger) — deferred; it now feeds the Confirmed badge so
  precision matters; revisit deliberately if auto-verify volume is the bottleneck.
- **Date-aware ad parsing** — "belt changed in the last N years"; free text rarely dates work,
  so evidence only downranks for now.
- **Per-variant power/year precision** beyond fuel + mileage/age.

---

## 6. Open decisions

- **D1** Maintenance label: distinct "Due unless serviced" badge (recommended) vs folded into
  Confirmed.
- **D2** *Resolved:* ad mentions service → downrank, never hide.
- **D3** Phase 3 mechanism: LLM gate vs curated stoplist vs both.
- **D4** Phase order (default 1→2→3, then 4–6).
- **D5** Authoritative feeds (Phase 4): which registries first, and manual import vs scripted.
- **D6** *(the big fork)* Does the **Reported** tier survive the curated-first shift? Two
  earlier asks pull apart: "show the general idea even from one low-tier source, labelled" (keep
  Reported) vs "surface only high-value stuff, not blog noise" (curated-first). Reconcilable —
  e.g. Reported survives but only for claims passing the Phase 3 relevance filter — or
  curated-first wins and the panel becomes Confirmed + Due only (accepting a thinner panel).
  Phase 4's "lead generator" language is contingent on this.

---

## 7. Non-goals

- Real-time per-request LLM calls on the serving path (stays a plain DB lookup).
- Asserting reliability / pricing advice. Kriko flags risks and says "get an inspection";
  it never says a car is good or bad.
- Lowering the verify bar to manufacture Confirmed claims.
