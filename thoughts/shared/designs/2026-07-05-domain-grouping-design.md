---
date: 2026-07-05
topic: "Domain Grouping for Issue Cards"
status: validated
---

## Problem Statement

The Hover Lite panel currently renders all risk cards as a flat, ungrouped list. With 15+ issues spanning engine, transmission, emissions, fuel system, and electrical domains, the user must scroll through everything to find what matters. The `domain` field on every `RiskItem` is already present in the API response — we're not using it for organization.

## Constraints

- **No backend changes** — grouping is purely a presentation concern. The API contract (`AnalyzeResponse.risks: list[RiskItem]`) stays flat.
- **No framework** — vanilla JS Shadow DOM, no React/Vue/Svelte. All DOM construction is `document.createElement` + `innerHTML`.
- **No build step** — the extension ships as-is; no bundling or preprocessing.
- **Backward compatible** — existing persisted state (`chrome.storage.session` cached results) must render correctly without migration.
- **Card state preserved** — per-card expand/collapse state (tracked by flat array index) must continue working.

## Approach

**Pure frontend grouping in `hover_lite.js`.** Group risks by `RiskItem.domain` at render time, insert collapsible section headers between groups. No changes to any backend file, `risk_card.js`, or `icons.js`.

**Why this over the alternatives:**
- Backend grouping changes the API contract for no benefit — grouping is a UI concern
- `domainIconSvg()` already exists in `icons.js` for every known domain value
- The sort order (strength → severity) is already correct within each domain; we only need to wrap groups visually
- Zero-risk change: if the grouping has a bug, the flat list is trivially restorable

## Architecture

### Data flow (unchanged until render step)

```
Backend → Flat RiskItem[] → background.js cache → hover_lite.js
                                                          |
                                                    groupRisksByDomain()
                                                          |
                                                    Map<domain, RiskItem[]>
                                                          |
                                                    render grouped DOM
```

The underlying `state.result.risks` stays a flat array. Grouping is computed fresh on every `renderRisksList()` call.

### State additions

```javascript
// New state field:
openDomains: new Set(),  // which domain group headers are expanded
```

**Initial population** — computed on first render:
- Domains that contain at least one `confirmed` or `due` item start expanded
- Pure-`reported` domains start collapsed (noise reduction)
- User can toggle any domain manually

**Not persisted** — `openDomains` is always recomputed from the current result. This means:
- No migration needed for cached results
- If a domain gets no actionable items in a future analysis, it auto-collapses
- The `openIds` set (per-card expand) is unchanged and still works by flat index

### Domain display order

```javascript
const DOMAIN_DISPLAY_ORDER = [
  "engine",           // Powertrain — most critical
  "transmission",     // Powertrain — equally critical
  "fuel system",      // Running cost + reliability
  "emissions",        // Expensive repairs (DPF, EGR, AdBlue)
  "turbocharger",     // High-cost failure
  "cooling",          // Can cause catastrophic engine damage
  "electrical",       // Growing modern-car problem area
  "suspension",       // Ride comfort + safety
  "brakes",           // Safety
  "steering",         // Safety
  "body/structure",   // Structural integrity
  "interior",         // Comfort / quality
  "manufacturing",    // General build quality
  "general",          // Catch-all
];
```

Unknown domains get sort key `999` and appear at the end.

### DOM structure per domain group

```html
<div class="lite-domain-group" data-domain="${domain}" data-open="${expanded ? "1" : "0"}">
  <button type="button" class="lite-domain-head" aria-expanded="${expanded ? "true" : "false"}">
    <span class="lite-domain-icon">${domainIconSvg(domain, { size: 15 })}</span>
    <span class="lite-domain-name">${displayLabel(domain)}</span>
    <span class="lite-domain-count">Count · ${risks.length}</span>
    <span class="lite-domain-toggle">${expanded ? "–" : "+"}</span>
  </button>
  <div class="lite-domain-bodywrap">
    <div class="lite-domain-bodyclip">
      <div class="lite-domain-body">
        <!-- risk cards here, rendered identically to current flat list -->
      </div>
    </div>
  </div>
</div>
```

### Collapse/expand animation

Uses the same `grid-template-rows` trick as risk card bodies (proven pattern in existing codebase):

```css
.lite-domain-bodywrap {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows 250ms var(--ease-out);
}
.lite-domain-group[data-open="1"] .lite-domain-bodywrap {
  grid-template-rows: 1fr;
}
.lite-domain-bodyclip { overflow: hidden; }
```

### Expand All / Collapse All changes

| Before | After |
|---|---|
| `expandAll()`: opens all cards | Opens all domain groups + all cards |
| `collapseAll()`: closes all cards | Closes all domain groups + all cards (groups collapse entirely, cards within collapse too) |

## Components and responsibilities

### `hover_lite.js` — the only file with logic changes

| Function | Change |
|---|---|
| `renderRisksList()` | Wrap flat iteration in domain-grouped loop; render headers before each group's cards |
| `expandAll()` | Add `state.openDomains = new Set(allDomains)` |
| `collapseAll()` | Add `state.openDomains = new Set()` |
| (new) `groupRisksByDomain(risks)` | Returns `Map<string, RiskItem[]>` preserving original internal sort |
| (new) `toggleDomain(domain)` | Toggle `state.openDomains`, re-render groups in place |
| (new) `computeDefaultOpenDomains(groups)` | Returns `Set<string>` — domains with confirmed/due items |

### `hover_lite.css` — new styles only

| Rule | Purpose |
|---|---|
| `.lite-domain-group` | Section container with top margin separating groups |
| `.lite-domain-head` | Clickable header row: icon + name + count + toggle |
| `.lite-domain-head:hover` | Hover state for pointer feedback |
| `.lite-domain-bodywrap` | Grid-collapsible wrapper (0fr → 1fr animation) |
| `.lite-domain-bodyclip` | Overflow hidden for animation |
| `.lite-domain-body` | Flex column gap for cards within group |
| `.lite-domain-group[data-open="0"] .lite-domain-bodywrap` | Collapsed state |

### Files with NO changes

- `risk_card.js` — card rendering unchanged, still called per-risk
- `icons.js` — `domainIconSvg()` already exists for all domains
- `hover_lite.js` — `renderRiskCard` import and usage unchanged
- `main.py`, `schemas.py`, `resolver.py`, `matcher.py` — backend untouched
- `background.js`, `content.js` — no behavior change

## Data flow (detailed render path)

```
state.result.risks (flat array, sorted by strength→severity)
        │
        ▼
groupRisksByDomain(risks)
  → Map: "engine" → [...], "transmission" → [...], "fuel system" → [...]
  → Internal sort preserved within each group (already correct from backend)
        │
        ▼
Compute default open domains (first render only)
  → engine: has confirmed → open
  → transmission: has reported only → closed
  → fuel system: has due → open
        │
        ▼
Iterate groups in DOMAIN_DISPLAY_ORDER:
  for each [domain, risks]:
    1. Create .lite-domain-group with data-open state
    2. Create .lite-domain-head with icon/name/count/toggle
    3. Wire click handler on head → toggleDomain(domain)
    4. Create .lite-domain-bodywrap → .lite-domain-body
    5. forEach risks with global index:
       - Create .lite-risk-anim with animation delay
       - renderRiskCard(risk, { open: state.openIds.has(globalIdx), compact })
       - Wire toggle button → toggleOne(globalIdx, cardEl)
       - Append to .lite-domain-body
    6. Append group to risksListEl
```

## Error handling

- **Empty domain group**: If a domain has 0 risks (shouldn't happen since we only iterate non-empty groups), skip rendering.
- **Unknown domain**: Falls into sort position 999 (end of list), rendered with "wrench" icon as fallback.
- **No risks at all**: `renderRisksList()` already handles `state.pipeline !== "result"` early-return; grouping never runs.
- **Single-domain result**: Renders one group header with all cards — slightly more header overhead than current flat list, but consistent UX.
- **Race condition on toggle**: Click handler on domain head toggles `state.openDomains` then re-renders. Risk card toggle handlers are unaffected since they reference flat indices.

## Testing strategy

- **Manual testing checklist**:
  - Verify domain groups render in the defined order
  - Verify each domain shows correct count and icon
  - Verify collapse/expand animation on domain headers
  - Verify per-card expand/collapse still works within groups
  - Verify Expand All opens both groups and cards
  - Verify Collapse All closes both
  - Verify pure-reported domains start collapsed
  - Verify mixed-strength domains start expanded
  - Verify single-risk result renders correctly (one group, one card)
  - Verify "no results" state renders correctly (no groups)
  - Verify loading skeleton state (still 3 shimmer bars)
  - Verify error state (error message replaces list)
  - Verify compact mode still works (cards within groups)
  - Verify staggered entrance animation looks correct with groups
  - Verify on multiple browser window widths (panel is draggable/responsive)

- **No unit tests** — the extension has no test runner. This is manual QA.

## Open questions

- **Should we animate domain header transitions?** Yes — the grid-template-rows animation matches the card expand pattern. Adds ~250ms of smoothness.
- **Should we sort risks differently within groups?** No — the current (strength, severity) sort is correct. Backend already orders by these fields.
- **What about the count bar at top?** Unchanged — it aggregates total high/medium/low across all groups. Users can still see severity distribution at a glance.
- **Should hovering over a domain head highlight all cards in that domain?** Nice-to-have but not in scope. Adds complexity for marginal UX gain.
