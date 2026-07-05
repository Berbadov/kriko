---
date: 2026-07-05
topic: "Issue Card Deduplication and Grouping"
status: draft
---

## Problem Statement

Users see many issue cards that say essentially the same thing — a "garbage" of near-duplicate cards rather than a concentrated, scannable list. This undermines trust and makes the product feel low quality.

**Two sources of duplication:**

1. **Same-topic claims across sibling parts** — e.g., the EA211 YAML has 6 timing-belt-related claims ("Timing belt design flaw", "Timing belt wear and chirp", "Timing belt failure due to camshaft gear defect", "Timing belt replacement interval critical", "Timing Belt Longevity Misrepresentation", "Timing belt failure due to camshaft gear defect"). These are slightly different angles on the same theme, but to a buyer they read as "lots of timing belt cards."

2. **Same claim from multiple matched variants** — When the matcher finds multiple candidates (ambiguous match), claims are unioned across all candidates. The `dict[int, Claim]` dedup catches same-claim-id duplicates, but near-identical claims from different parts still pass through.

**Design gap:** All dedup logic runs offline in `knowledge/dedup.py`. The serving plane (`/analyze` → `resolver.py`) has zero dedup. The frontend (`hover_lite.js` → `risk_card.js`) renders every `RiskItem` as an independent flat card with no grouping.

## Constraints

- **No LLM on the serve path** — dedup must be algorithmic (Jaccard, token overlap), not ML-based
- **Must preserve strength distinction** — "confirmed" vs "reported" vs "due" are meaningful and should never be lost
- **Zero new dependencies** — reuse existing logic from `knowledge/dedup.py`
- **Must not break the API contract** — `AnalyzeResponse` schema stays unchanged
- **Frontend changes must be backward-compatible** — older API responses without grouped data still render correctly
- **Performance** — dedup must complete in <10ms; the serve path currently takes ~30ms total

## Approach

I'm using a **three-layer strategy**, each handling a different level of the problem:

| Layer | Where | What | Effort |
|-------|-------|------|--------|
| 1 — Title dedup | `resolver.py` | Merge similar claims by Jaccard similarity | Small |
| 2 — Domain grouping | `hover_lite.js` + `risk_card.js` | Visually group cards under expandable domain sections | Medium |
| 3 — Cross-file warnings | `sync.py` | Build-time alert when part files have near-dup titles | Small |

**Why three layers instead of one:** Layer 1 removes exact/near-exact duplicates (same issue, different wording). Layer 2 organizes what's left so "6 timing belt variations" become "1 timing belt section with 6 sub-items" — much more scannable. Layer 3 prevents the problem from growing.

## Architecture

### Layer 1: Backend title-similarity dedup

```
resolver.py
  resolve_claims() → List[ClaimResult]
                           │
                    [new] _deduplicate_results()
                           │
                    List[ClaimResult] (merged)
                           │
                    main.py → _claim_to_risk()
```

**How it works:**

Extract the title tokenization + Jaccard logic from `knowledge/dedup.py` into a shared utility that both the offline pipeline and serving plane can use.

Add a new function `_deduplicate_results(results: list[ClaimResult]) → list[ClaimResult]` in `resolver.py`:

1. Group `ClaimResult` objects by domain
2. Within each domain, compute pairwise Jaccard similarity on tokenized titles
3. Merge groups where Jaccard ≥ 0.4 (same threshold as offline dedup)
4. When merging, **preserve the best** from each group:
   - Title: keep the title of the highest-severity claim (ties: most sources)
   - Severity: take the highest severity in the group
   - Strength: keep the strongest ("confirmed" > "due" > "due_stated" > "reported")
   - Rationale: concatenate unique paragraphs, deduping near-duplicate text
   - Inspection advice: concatenate unique advice
   - Sources: merge all unique source URLs
   - Confidence: keep the highest confidence value
   - Domain: unchanged (all merged claims share domain)

**Edge cases:**
- Empty input → return `[]`
- Single claim → return as-is
- All claims in a group are maintenance items → merge as maintenance
- Mixed confirmed/reported → keep strongest strength label, document both statuses in rationale

### Layer 2: Frontend domain grouping

```
hover_lite.js
  renderBody() → renders risks as:
    [NEW] <section class="lite-domains">
            <div class="lite-domain" data-domain="engine">
              <button class="lite-domain-head">Engine (3)</button>
              <div class="lite-domain-body">
                [existing risk cards]
              </div>
            </div>
            ...
          </section>
```

**How it works:**

Before rendering, group `state.result.risks` by `domain` field. For each domain:
- Create an expandable section with the domain name and count
- Render existing risk cards inside the section body
- Default: all sections open, user can collapse individual domains

**Domain display names & icons:**
| domain value | display name | icon |
|---|---|---|
| engine | Engine | piston/gear |
| transmission | Transmission | gear |
| emissions | Emissions | exhaust |
| electrical | Electrical | bolt |
| fuel system | Fuel System | fuel |
| *other* | capitalize | generic warning |

**Design:**
- Domain heads are sticky within the scroll panel
- Each domain shows a high/medium/low mini count (reuse existing severity counts)
- Clicking a domain head toggles its body open/closed
- Individual risk cards inside remain unchanged — `risk_card.js` needs no modification

### Layer 3: Cross-file duplicate warnings

In `sync.py`, after loading all part YAMLs but before writing to DB:
1. Collect all claim titles across all parts
2. Compute pairwise Jaccard similarity for same-domain claims across different parts
3. Log a `warning` for any pair with Jaccard ≥ 0.4
4. Include the part file paths and claim keys in the warning

This is purely informational — it doesn't block sync. It helps the knowledge pipeline operator know when two parts have overlapping content that should be consolidated.

## Data Flow

```
User clicks analyze
  → content.js scrapes DOM → ad_metadata
  → background.js → POST /analyze
    → match_variant() → MatchResult
    → resolve_claims() → List[ClaimResult]
    → [NEW] _deduplicate_results() → List[ClaimResult] (fewer items)
    → _claim_to_risk() → List[RiskItem]
    → AnalyzeResponse
  → background.js → chrome.storage.session
  → hover_lite.js reads result
    → [NEW] group risks by domain
    → [NEW] render domain sections
    → render each risk card inside its section
```

## Example Scenario

**Before (current):** 14 cards flat list — 6 timing belt variations, 3 wastegate variations, 2 water pump variations, 2 carbon build-up variations, 1 PCV valve

**After (dedup+group):**
```
🛞 Engine (8)
  ├── Timing belt replacement [high] — 5 merged sources
  ├── Turbo wastegate corrosion/seizure [medium] — 2 merged sources
  ├── Water pump cracking/leaking [high] — 3 merged sources
  ├── Carbon build-up on valves [medium] — 4 merged sources
  ├── Ignition coil failure [medium]
  ├── PCV valve failure [medium]
  ├── Camshaft adjuster failure [medium]
  └── Thermostat heater failure [medium]

⚙️ Transmission (2)
  ├── DQ200 mechatronics valve body cracking [high]
  └── DSG shuddering and jerking [high]

🔧 Emissions (2)
  ├── OPF clogging on short trips [medium]
  └── EGR valve clogging [medium]

🔌 Electrical (1)
  └── 48V hybrid communication failures [high]
```

## Error Handling Strategy

- **Backend dedup failure**: Wrap `_deduplicate_results()` in try/except. If it throws, log the error and return the original list (fail-open — better to show duplicates than nothing)
- **Frontend grouping failure**: Same fail-open — if the grouping logic throws, fall back to flat render
- **Tokenization of empty/null titles**: Handle with guard clauses, return Jaccard 0.0
- **Edge case — all claims merged into one**: The dedup should never collapse all claims into a single group; Jaccard threshold prevents that for dissimilar domains

## Testing Strategy

### Backend tests
1. **Unit test — identical titles**: Two ClaimResults with same title → merged to one
2. **Unit test — similar titles**: "Timing belt failure" vs "Timing belt replacement" → merged (Jaccard ≥ 0.4)
3. **Unit test — different titles**: "Water pump leak" vs "Ignition coil failure" → not merged
4. **Unit test — different domains**: Same title, different domain → not merged
5. **Unit test — strength preservation**: "confirmed" + "reported" → "confirmed"
6. **Unit test — empty input**: Returns `[]`
7. **Unit test — single input**: Returns unchanged
8. **Integration test**: `resolve_claims()` + `_deduplicate_results()` full pipeline

### Frontend tests
- Visual test: open the panel on a listing with 10+ risks, verify domain sections appear
- Collapse/expand: click each domain head, verify body toggles
- Count badges: verify domain section shows correct count
- Empty domain: verify no empty sections rendered

## Open Questions

1. **Should we add a `merged` field to `RiskItem` schema?** I'm leaning no — the merge should be transparent. But we could add `merged_count: int` optionally to show "5 sources merged" in the card. Let's skip for now, revisit if users want to see it.

2. **Should the frontend or backend own the grouping?** I'm having the backend own dedup (semantic merge) and the frontend own grouping (visual layout). This separation of concerns keeps the API clean and the UI flexible.

3. **Threshold sensitivity:** Jaccard 0.4 is inherited from the offline pipeline. If we see false positives (different claims merged), we bump to 0.5. If false negatives (duplicates not caught), we drop to 0.35. Ship at 0.4 and adjust from production feedback.

4. **Should the summary count change?** Currently summary says "X confirmed issues, Y maintenance items due, Z unverified reports." This should reflect post-dedup counts — the summary in the snapshot should match what the user sees.

## Implementation Plan

### Phase 1: Extract tokenizer to shared module
- Move `_title_tokens()` and `title_similar()` from `knowledge/dedup.py` to `backend/core/title_sim.py`
- Both `knowledge/dedup.py` and `resolver.py` import from the shared location
- Verify offline dedup still works (import path change only)

### Phase 2: Backend dedup in resolver.py
- Add `_deduplicate_results()` to `resolver.py`
- Call it at the end of `resolve_claims()` before returning
- Wrap in try/except with fail-open logging
- Update `_build_summary()` in `main.py` to count post-dedup risks

### Phase 3: Frontend domain grouping in hover_lite.js
- Add domain grouping logic in the `renderBody()` function
- Create new CSS for domain sections (reuses existing component patterns)
- Wire collapse/expand toggle
- Ensure backward compatibility (no grouped data → flat render)

### Phase 4: Cross-file warning in sync.py
- Add duplicate detection loop after loading all YAMLs
- Log warnings with file paths and claim keys

### Phase 5: Testing
- Write new backend tests for dedup
- Manual frontend testing (open panel, verify sections)
