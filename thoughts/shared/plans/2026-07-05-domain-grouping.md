# Implementation Plan: Domain Grouping for Issue Cards

**Design doc:** `thoughts/shared/designs/2026-07-05-domain-grouping-design.md`
**Files changed:** `extension_ui/hover_lite/hover_lite.js` (+~90 lines), `extension_ui/hover_lite/hover_lite.css` (+~80 lines)
**No backend changes needed.**

---

## Step 1: Add `openDomains` state and constants to `hover_lite.js`

### What to change

After line 33 (`openIds: new Set(),`), add:
```js
openDomains: new Set(),   // expanded domain groups
```

After line 41 (end of state object), insert constants:
```js
const DOMAIN_DISPLAY_ORDER = [
  "engine", "transmission", "fuel system", "emissions",
  "turbocharger", "cooling", "electrical", "suspension",
  "brakes", "steering", "body/structure", "interior",
  "manufacturing", "general",
];
```

### How to verify

File loads without syntax errors. State object has `openDomains` field.

---

## Step 2: Add helper functions to `hover_lite.js`

Add after the constants (before element refs section, around line 55):

```js
function displayLabel(domain) {
  return domain.replace(/(^|\/)(.)/g, (_, p, c) => c.toUpperCase()).replace(/\//g, ' / ');
}

function groupRisksByDomain(risks) {
  const map = new Map();
  for (const r of risks) {
    const domain = (r.domain || "general").toLowerCase().trim();
    if (!map.has(domain)) map.set(domain, []);
    map.get(domain).push(r);
  }
  return map;
}

function computeDefaultOpenDomains(groups) {
  const open = new Set();
  for (const [domain, risks] of groups) {
    const hasActionable = risks.some(r => r.strength === "confirmed" || r.strength === "due");
    if (hasActionable) open.add(domain);
  }
  return open;
}

function domainSortKey(domain) {
  const idx = DOMAIN_DISPLAY_ORDER.indexOf(domain);
  return idx === -1 ? 999 : idx;
}
```

### How to verify

`displayLabel("fuel system")` → `"Fuel System"`, `displayLabel("body/structure")` → `"Body / Structure"`.

---

## Step 3: Modify `renderRisksList()` — core change

### What to change

Replace the `state.result.risks.forEach(...)` block (lines 938-947) with domain-grouped rendering.

The full replacement logic:

1. **Group risks**: `const groups = groupRisksByDomain(state.result.risks)`
2. **Initialize open domains** (only if `state.openDomains.size === 0`): `state.openDomains = computeDefaultOpenDomains(groups)`
3. **Sort domain keys**: `[...groups.keys()].sort((a, b) => domainSortKey(a) - domainSortKey(b))`
4. **Iterate sorted domains**, for each:
   - Create `.lite-domain-group[data-open]` container
   - Create `.lite-domain-head` button with icon + name + count + toggle
   - Wire click handler on head → toggle `data-open` + aria-expanded + toggle text
   - Create `.lite-domain-bodywrap > .lite-domain-bodyclip > .lite-domain-body`
   - Within body, render cards using `renderRiskCard()` (identical to current code)
   - Use `globalIdx` (flat counter, not per-group counter) for card index
   - Staggered animation uses `globalIdx` for delay

All non-result branches (analyzing/error/idle) stay exactly as-is.

### How to verify

Panel shows domain section headers. Cards appear nested under their domain. Domain order matches `DOMAIN_DISPLAY_ORDER`.

---

## Step 4: Modify `setAllOpen()` to toggle domain groups

### What to change

Replace `setAllOpen()` (lines 970-982) to also manage `state.openDomains`:

```js
function setAllOpen(open) {
  if (!state.result) return;
  state.openIds = open
    ? new Set(state.result.risks.map((_, i) => i))
    : new Set();
  // Toggle domain groups
  if (open) {
    const groups = groupRisksByDomain(state.result.risks);
    state.openDomains = new Set(groups.keys());
  } else {
    state.openDomains = new Set();
  }
  // Mutate domain groups in place (no re-render to preserve entrance animations)
  const groups = risksListEl.querySelectorAll(".lite-domain-group");
  groups.forEach((g) => {
    const domain = g.dataset.domain;
    const isOpen = state.openDomains.has(domain);
    g.dataset.open = isOpen ? "1" : "0";
    const head = g.querySelector(".lite-domain-head");
    if (head) {
      head.setAttribute("aria-expanded", isOpen ? "true" : "false");
      const toggle = head.querySelector(".lite-domain-toggle");
      if (toggle) toggle.textContent = isOpen ? "–" : "+";
    }
  });
  // Mutate cards in place
  const cards = risksListEl.querySelectorAll(".lite-rc");
  cards.forEach((card) => updateRiskCard(card, { open }));
  renderRisksHeader();
}
```

### How to verify

- Click "Expand All" → all domain groups open, all cards expand
- Click "Collapse All" → all domain groups close, all cards collapse
- Animation is smooth (DOM mutation, not innerHTML re-render)

---

## Step 5: Add domain group CSS to `hover_lite.css`

### What to change

Append to end of file (before EOF):

```css
/* ─────────────────────────────────────────────
   Domain groups (collapsible sections)
   ───────────────────────────────────────────── */
.lite-domain-group {
  display: flex;
  flex-direction: column;
}

.lite-domain-head {
  all: unset;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  margin-top: 16px;
  background: var(--bg-item);
  border: 1px solid var(--border);
  border-radius: 6px;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--fg-subtle);
  letter-spacing: 0.5px;
  transition: border-color var(--dur-fast), color var(--dur-fast);
}
.lite-domain-head:hover {
  border-color: #3a414c;
  color: var(--fg);
}

.lite-domain-icon {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  color: var(--fg-subtle);
}
.lite-domain-head:hover .lite-domain-icon {
  color: var(--fg);
}

.lite-domain-name {
  font-weight: 600;
  font-size: 11.5px;
  color: var(--fg);
  flex: 0 0 auto;
}

.lite-domain-count {
  color: var(--fg-muted);
  font-size: 10.5px;
  flex: 1;
}

.lite-domain-toggle {
  flex: 0 0 auto;
  font-size: 16px;
  line-height: 1;
  color: var(--fg-subtle);
}

.lite-domain-bodywrap {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows 250ms var(--ease-out);
}
.lite-domain-group[data-open="1"] .lite-domain-bodywrap {
  grid-template-rows: 1fr;
}
.lite-domain-group:first-child .lite-domain-head {
  margin-top: 0;
}

.lite-domain-bodyclip {
  overflow: hidden;
}

.lite-domain-body {
  display: flex;
  flex-direction: column;
  gap: 11px;
  padding: 8px 0;
}
```

### How to verify

Loading extension shows properly styled domain headers matching the dark theme. No layout breaking.

---

## Step 6: Manual verification checklist

1. **Load extension**: `chrome://extensions` → Load unpacked → `extension_ui/`
2. **Navigate** to a Sahibinden listing (or any page for testing with cached data)
3. **Open panel**: Verify domain groups render, not flat list
4. **Domain order**: Engine first, transmission second, etc.
5. **Default expand state**: Domains with confirmed/due items expanded; pure-reported collapsed
6. **Toggle domain**: Click header → section collapses/expands with animation
7. **Toggle card**: Click card +/− → card expands/collapses within its domain group
8. **Expand All**: Opens all domains + all cards
9. **Collapse All**: Closes everything
10. **Single domain**: If only one domain has risks, one group renders
11. **No results**: Empty/error/idle states unchanged
12. **Console**: No errors in dev console
13. **Compact mode**: Toggle compact → cards within groups render compact

---

## Edge cases

| Case | Expected behavior |
|------|------------------|
| Unknown domain value (e.g., "safety") | Appears at end, gets "wrench" icon fallback |
| Only one domain with risks | Single group header + cards |
| All domains collapsed | Domain headers visible, no cards shown |
| Domain with 1 risk | Shows count "· 1", header + card |
| Domain with 20 risks | Scroll within panel body, no layout issues |
| Rapid toggle clicks | DOM mutation is synchronous, no race conditions |
| Preexisting cached result | `openDomains` computed fresh on render from result data |
| Very long domain names | CSS handles overflow with flex; name truncates if needed |
