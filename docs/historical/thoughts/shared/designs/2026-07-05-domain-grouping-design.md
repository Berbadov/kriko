> TL;DR (archived 2026-09-25): Design (2026-07-05, validated) for grouping the Hover Lite
panel's flat risk list into collapsible domain sections — pure frontend in `hover_lite.js`
(group at render, `openDomains` state, fixed display order, grid-rows animation),
no backend/API/card changes, flat indices preserved.

---
date: 2026-07-05
topic: "Domain Grouping for Issue Cards"
status: validated
---

## Problem Statement

Hover Lite renders 15+ risk cards flat across engine/transmission/emissions/fuel/electrical; users scroll everything to find what matters. Every `RiskItem` already carries `domain` — unused for organisation.

## Constraints

- **No backend changes** — `AnalyzeResponse.risks` stays flat; grouping is presentation-only.
- Vanilla JS Shadow DOM, no framework, no build step; backward-compatible with cached `chrome.storage.session` results; per-card expand state (flat indices) keeps working.

## Approach

**Pure frontend grouping in `hover_lite.js`:** group by `domain` at render, insert collapsible headers. Alternatives rejected: backend grouping changes the API for no benefit; `domainIconSvg()` already exists; backend sort (strength → severity) is already right per group; flat list trivially restorable if buggy.

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

**Initial population** — computed on first render: domains with at least one `confirmed`/`due` item start expanded; pure-`reported` domains start collapsed (noise reduction); user-togglable. **Not persisted** — recomputed from the current result (no migration; auto-collapse when unactionable). `openIds` (per-card) unchanged.

### Domain display order

engine, transmission, fuel system, emissions, turbocharger, cooling, electrical, suspension, brakes, steering, body/structure, interior, manufacturing, general. Unknown domains get sort key `999` and appear at the end (wrench fallback icon).

### DOM structure per domain group

`.lite-domain-group[data-open]` > `.lite-domain-head` button (icon + name + count + toggle) + `.lite-domain-bodywrap > .lite-domain-bodyclip > .lite-domain-body` (cards identical to flat list).

### Collapse/expand animation

Reuses the card-body `grid-template-rows 0fr→1fr` trick (250ms).

**Expand/Collapse All** now toggles domain groups + cards (in-place DOM mutation, no re-render).

### Expand All / Collapse All changes

| Before | After |
|---|---|
| `expandAll()`: opens all cards | Opens all domain groups + all cards |
| `collapseAll()`: closes all cards | Closes all domain groups + all cards (groups collapse entirely, cards within collapse too) |

## Components and responsibilities

`hover_lite.js` only: `renderRisksList()` (grouped loop), `expandAll`/`collapseAll` (+ `openDomains`), new `groupRisksByDomain` / `toggleDomain` / `computeDefaultOpenDomains`.

### `hover_lite.js` — the only file with logic changes

Same as above — the table is the contract; `renderRiskCard` import and usage unchanged.

### `hover_lite.css` — new styles only

Section container, clickable header row, grid-collapsible wrapper, card gap (new rules only, listed above).

### Files with NO changes

`risk_card.js`, `icons.js`, `main.py`/`schemas.py`/`resolver.py`/`matcher.py`, `background.js`/`content.js`.

## Data flow (detailed render path)

Flat risks (backend-sorted) → group preserving order → default-open computation (first render) → iterate in display order: container + header + toggle wiring + body; cards rendered with **global** indices (flat counter) so `toggleOne`/`setAllOpen`/stagger delays work unchanged. Non-result branches (analyzing/error/idle) untouched.

## Error handling

- Empty groups never iterated; unknown domains → end + fallback icon; no-risks/loading/error states unchanged; single-domain result = one header + cards (consistent UX); synchronous toggle ⇒ no races.

## Testing strategy

Manual QA checklist: group order, icons/counts, animations, per-card toggle inside groups, Expand/Collapse All, default states (reported-collapsed, mixed-expanded), single-risk, empty, skeleton, error, compact mode, stagger animation, widths. No unit tests (extension has no runner).

## Open questions

- Animate headers? Yes — matches card pattern (~250ms). Re-sort within groups? No — backend order stands. Top count bar? Unchanged. Hover-highlight domain? Nice-to-have, out of scope.
