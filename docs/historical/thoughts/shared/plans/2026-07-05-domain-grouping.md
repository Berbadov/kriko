> TL;DR (archived 2026-09-25): Implementation plan (2026-07-05) for frontend-only domain
grouping: `openDomains` state + display order (Step 1), helper functions (Step 2), grouped
`renderRisksList` (Step 3), domain-aware `setAllOpen` (Step 4), group CSS (Step 5), manual QA
(Step 6). Backend untouched; `hover_lite.js` +~90 / `.css` +~80 lines.

# Implementation Plan: Domain Grouping for Issue Cards

**Design doc:** `thoughts/shared/designs/2026-07-05-domain-grouping-design.md`
**Files changed:** `extension_ui/hover_lite/hover_lite.js` (+~90 lines), `extension_ui/hover_lite/hover_lite.css` (+~80 lines)
**No backend changes needed.**

---

## Step 1: Add `openDomains` state and constants to `hover_lite.js`

### What to change

After line 33 (`openIds: new Set(),`): `openDomains: new Set(),   // expanded domain groups`. After the state object (~line 41): `DOMAIN_DISPLAY_ORDER` (engine, transmission, fuel system, emissions, turbocharger, cooling, electrical, suspension, brakes, steering, body/structure, interior, manufacturing, general).

### How to verify

File loads without syntax errors; state object has `openDomains`.

---

## Step 2: Add helper functions to `hover_lite.js`

Add before element refs (~line 55): `displayLabel(domain)` (capitalize + ` / ` spacing), `groupRisksByDomain(risks)` (→ `Map`, missing ⇒ `"general"`), `computeDefaultOpenDomains(groups)` (confirmed/due ⇒ open), `domainSortKey(domain)` (order index, unknown ⇒ 999). (Full functions — see git history.)

### How to verify

`displayLabel("fuel system")` → `"Fuel System"`, `displayLabel("body/structure")` → `"Body / Structure"`.

---

## Step 3: Modify `renderRisksList()` — core change

### What to change

Replace the flat `risks.forEach` (lines 938-947): group → init `openDomains` if empty → sort domains → per domain create `group[data-open]` + head button (icon/name/count/toggle) with click → toggle state/aria/glyph → bodywrap > bodyclip > body → render cards via `renderRiskCard()` with **global** indices + stagger delays. Non-result branches unchanged.

### How to verify

Panel shows domain headers; cards nested under their domain; order matches `DOMAIN_DISPLAY_ORDER`.

---

## Step 4: Modify `setAllOpen()` to toggle domain groups

### What to change

Replace (lines 970-982): manage `state.openDomains` alongside `openIds` (open ⇒ all domains; closed ⇒ none); mutate groups + cards in place (no re-render, preserves animations); `renderRisksHeader()`. (Full function — see git history.)

### How to verify

Expand All opens all groups + cards; Collapse All closes everything; animation smooth (DOM mutation, not re-render).

---

## Step 5: Add domain group CSS to `hover_lite.css`

### What to change

Append: `.lite-domain-group` (flex column), `.lite-domain-head` (clickable row: icon/name/count/toggle, hover states), grid-collapse `.lite-domain-bodywrap` (`0fr`→`1fr`, 250ms) + `.lite-domain-bodyclip` overflow, `.lite-domain-body` (flex, gap 11px), first-child margin reset. (Full rules — see git history.)

### How to verify

Dark-theme headers; no layout breakage.

---

## Step 6: Manual verification checklist

Load unpacked `extension_ui/` → Sahibinden listing → panel shows groups in order; default states (confirmed/due open, pure-reported closed); domain + card toggles; Expand/Collapse All; single-domain; empty/error/idle/compact/skeleton states; stagger animation; widths; clean console.

---

## Edge cases

| Case | Expected behavior |
|------|------------------|
| Unknown domain | End of list, wrench fallback icon |
| Single domain / single risk | One header (+ count "· 1") + cards |
| All collapsed | Headers visible, no cards |
| 20-risk domain | Panel scrolls, no layout issues |
| Rapid toggles | Synchronous DOM mutation, no races |
| Cached result | `openDomains` recomputed fresh from data |
| Long names | Flex truncation |
