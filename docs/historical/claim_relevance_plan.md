> TL;DR (archived 2026-09-25): Plan making served claims match the product principle
(config-/mileage-specific risks + due maintenance the ekspertiz can't cheaply cover).
Levers: `ListingContext` + `applies_when` gating (Phase 1), `kind: maintenance` due-claims
with downrank-never-hide evidence (Phase 2, D2 resolved), `gate_inspection_value` noise filter
(Phase 3). Backend-only Phases 1–2; interim = hand-tombstone noise now. Decisions D1–D4 below.

# Plan — Make claim selection match the product principle

Goal: from "whatever a blog mentioned" (warning lights, fluids, injector bench tests) to **config- and mileage-specific known risks + due-maintenance items a buyer can't cheaply get from the standard pre-purchase inspection** (`CLAUDE.md`).

Target for a high-mileage diesel auto: *timing belt due unless the ad shows it*, *EDC wear at this mileage*, *AdBlue/EGR/DPF grief on this engine*. Stop: *brake fluid* / *ESP light* / *injector health* (ekspertiz covers those).

## Key enabling fact

`ad_metadata` already arrives at `/analyze` with everything needed, scraped by `content.js` but ignored: `mileage_km`, `annual_km`, `year` (gating); `description`, `equipment`, `damage_info` (maintenance evidence); `fuel_type`, `transmission`, `engine_volume_cc`, `power_hp` (config). Phases 1–2 are **backend-only**.

---

## Shared foundation: `ListingContext`

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

Built in `main.py` from `ad_metadata`; `resolve_claims(match, db)` → `resolve_claims(match, db, ctx)`.

---

## Phase 1 — Mileage/age gating (Lever A)  ·  backend only

Claims declare relevance windows so EDC-wear / DPF-clogging show only past biting mileage:

```yaml
applies_when:
  min_mileage_km: 120000
  max_mileage_km: null
  min_age_years: 6
```

Nullable DB columns (`sync.py` loads, `models.py` declares); resolver drops non-matching claims. **Fail-open**: missing mileage/age ⇒ show, never hide. **Deliverable includes authoring ~4 exemplar Megane-4 claims with real thresholds** (EDC wear 120k on EDC variants; AdBlue/EGR/DPF on diesels) — gating gates nothing without them; the blog pipeline won't produce them. Validates: EDC seed shows at 190k, hidden at 30k. Tests: shown ≥ threshold, hidden below, shown when unknown, age gating, untagged claims unaffected.

---

## Phase 2 — Maintenance-due claims (Lever B)  ·  backend only · builds on Phase 1

Flagship: "cam belt due unless the ad proves it was changed" — predicted-due, not observed-failure.

```yaml
kind: maintenance              # default: known_issue
maintenance:
  interval_km: 90000
  interval_years: 6
  evidence_keywords: ["triger değiş", "kayış değiş", "timing belt replaced", "cam belt"]
```

Nested block ⇒ single **JSON column** (not flat columns like `applies_when`). Per-engine grounding: belt claims only on belt engines (K9K/R9M belt; H5H 1.3 TCe is **chain** — confirm per engine).

**Resolver:** due if `mileage_km >= interval_km` OR `age_years >= interval_years`. Due + no evidence ⇒ show ("due — ad doesn't mention a recent change"). Due + evidence ⇒ **downrank, never hide** (D2 resolved): ad text is unverified seller claim and bare keywords misfire (`triger sesi` = belt *noise*, not service) — change-specific phrases only (`… değiş*`, `… replaced`). Not due ⇒ hide. Unknown mileage/age ⇒ fail-open ("interval-based — verify service history"). Recency limitation accepted: no date parsing, so evidence only ever downranks, never clears.

**Serving:** third strength `"due"` → **"Due unless serviced"** badge (D1); summary counts maintenance separately. Validates: diesel cam-belt claim shows at 190k plain, suppressed with "triger değişti". Tests: four due/evidence combos + fail-open + accent/case-tolerant matching.

---

## Phase 3 — Relevance / "inspection already covers this" filter (Lever C)  ·  offline pipeline

Stop brake-fluid/ESP/injector-bench at the source (what pipeline keeps, not serving; order-independent):

- New promote-time `gate_inspection_value(claim)` (offline LLM): inspection-catchable or generic-warning ⇒ `rejected` (tombstoned).
- Extend `gate_generic` to pure warning-light claims ("ESP/ABS light").
- Optional curated stoplist pre-filter; re-run `--skip-extraction` to re-grade (served brake/ESP/injector claims drop out).
- Tests: `eval_judge` golds — belt/EDC/AdBlue kept; brake-fluid/ESP/pads dropped.

---

## Interim (do now, no code) — make the panel look right today

Phases 1–2 add value but don't remove served brake/ESP/injector cards (that's Phase 3). They're `review`/`held` in YAML ⇒ tombstone by hand now (`status: rejected`) + re-sync. Demo clean immediately; Phase 3 makes it systematic.

## Suggested order (one at a time, your call)

**Phase 1** (plumbing Phase 2 needs + mileage-aware claims + exemplar set) → **Phase 2** (flagship belt/service claims) → **Phase 3** (systematic noise cleanup; standalone — first if noise is priority).

## Open decisions (pick as we reach them)

- **D1** — Maintenance label: distinct **"Due unless serviced"** badge (recommended) vs folded into Confirmed.
- **D2** — *Resolved:* ad mentions service ⇒ downrank to "confirm with a documented record", never hide.
- **D3** — Phase 3: LLM gate vs curated stoplist vs both.
- **D4** — Order: value-first (default) vs kill-noise-first.

## Out of scope (for now)

Cross-run score accumulation, recall/TSB sourcing, merge loosening (tracked elsewhere); per-variant power/year precision beyond fuel + mileage/age.
