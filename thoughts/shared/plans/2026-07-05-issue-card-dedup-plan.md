# Implementation Plan: Issue Card Dedup and Grouping

## Phase 1 — Shared title-similarity module (1 file, no deps)

**Task 1.1:** Create `backend/core/title_sim.py`
- Extract `_title_tokens()` and `title_similar()` from `knowledge/dedup.py`
- Both functions are identical — copy them verbatim
- No dependencies on sqlalchemy, dataclasses, etc.
- Import re + logging

**Task 1.2:** Update `knowledge/dedup.py` 
- Change import from local `_title_tokens`/`title_similar` to `from backend.core.title_sim import _title_tokens, title_similar`
- Keep `same_claim()` as-is (it uses the same tokenizer)
- Keep `_STOPWORDS` in dedup.py or move it to title_sim.py — either works

**Test 1.3:** Create `tests/test_title_sim.py`
- Test `_title_tokens()`: empty string, single word, with stopwords
- Test `title_similar()`: identical strings → 1.0, completely different → 0.0, "Timing belt failure" vs "Timing belt replacement" ≥ 0.4
- Test edge case: both empty → False

## Phase 2 — Backend dedup (1 file: resolver.py)

**Task 2.1:** Add import in `resolver.py`
- `from backend.core.title_sim import title_similar`

**Task 2.2:** Add `_deduplicate_results(results: list[ClaimResult]) → list[ClaimResult]` in `resolver.py`

Logic:
```
def _deduplicate_results(results: list[ClaimResult]) -> list[ClaimResult]:
    if len(results) <= 1:
        return results

    # Group by domain
    by_domain: dict[str, list[ClaimResult]] = {}
    for cr in results:
        by_domain.setdefault(cr.claim.domain or "unknown", []).append(cr)

    merged = []
    for domain, group in by_domain.items():
        # Within each domain, group by title similarity
        clusters: list[list[ClaimResult]] = []
        for cr in group:
            placed = False
            for cluster in clusters:
                if title_similar(cluster[0].claim.title, cr.claim.title):
                    cluster.append(cr)
                    placed = True
                    break
            if not placed:
                clusters.append([cr])
        
        for cluster in clusters:
            if len(cluster) == 1:
                merged.append(cluster[0])
                continue
            merged.append(_merge_cluster(cluster))
    
    return merged
```

**Task 2.3:** Add `_merge_cluster(cluster: list[ClaimResult]) → ClaimResult` in `resolver.py`

Merge strategy:
- Title: keep the title of the highest-severity claim (ties: most evidence/sources)
- Severity: max of all (high > medium > low)
- Strength: strongest wins ("confirmed" > "due" > "due_stated" > "reported")
- Rationale: join unique sentences, skip near-duplicate content
- Inspection advice: join unique advice with "; "
- Confidence: max of all
- Domain: unchanged (all in cluster share domain)
- Claim: use the representative Claim object from the merged result

**Task 2.4:** Call dedup at end of `resolve_claims()`:
```python
def resolve_claims(match, db, ctx=None):
    ...
    results = _apply_context(claims, ctx)
    return _deduplicate_results(results)  # NEW
```

Wrap in try/except: if dedup fails, log warning and return original list.

## Phase 3 — Update summary counts (1 file: main.py)

**Task 3.1:** In `run_analysis()` in `main.py`, ensure `_build_summary()` counts post-dedup risks

Currently the flow is:
```python
served = resolve_claims(match, db, ctx)
risks = [_claim_to_risk(cr, db) for cr in served]
```

The summary is built from `risks` (the RiskItem list), so it already uses post-dedup counts since dedup happens inside `resolve_claims()`. 

**Verify:** The summary is built from `risks` parameter in `_build_summary(state, match, risks)` — and `risks` comes from the deduped `served` list. No change needed.

## Phase 4 — Frontend domain grouping (2 files: hover_lite.js, hover_lite.css)

**Task 4.1:** Add domain grouping in `hover_lite.js` `renderBody()` function

After "summary-slot" section and before "details-slot", replace the flat `<section class="lite-risks">` with domain-grouped sections.

Logic:
```javascript
function renderRisksGrouped(risks) {
  if (!risks || !risks.length) return '';
  
  // Group by domain
  const grouped = {};
  for (const r of risks) {
    const d = r.domain || 'other';
    if (!grouped[d]) grouped[d] = [];
    grouped[d].push(r);
  }
  
  const domainLabels = {
    engine: { label: 'Engine', icon: 'engine' },
    transmission: { label: 'Transmission', icon: 'transmission' },
    emissions: { label: 'Emissions', icon: 'emissions' },
    electrical: { label: 'Electrical', icon: 'electrical' },
    'fuel system': { label: 'Fuel System', icon: 'fuel' },
  };
  
  let html = '<div class="lite-domain-groups">';
  for (const [domain, items] of Object.entries(grouped)) {
    const info = domainLabels[domain] || { label: domain.charAt(0).toUpperCase() + domain.slice(1), icon: null };
    const high = items.filter(r => r.severity === 'high').length;
    const med = items.filter(r => r.severity === 'medium').length;
    const low = items.filter(r => r.severity === 'low').length;
    
    html += `
      <div class="lite-domain-group" data-domain="${domain}">
        <button type="button" class="lite-domain-head" aria-expanded="true">
          <span class="lite-domain-icon">${iconSvg(info.icon || 'warning')}</span>
          <span class="lite-domain-name">${info.label}</span>
          <span class="lite-domain-count">${items.length}</span>
          <span class="lite-domain-sev">
            ${high ? `<span class="lite-domain-sev-dot" data-sev="high"></span>${high}` : ''}
            ${med ? `<span class="lite-domain-sev-dot" data-sev="medium"></span>${med}` : ''}
            ${low ? `<span class="lite-domain-sev-dot" data-sev="low"></span>${low}` : ''}
          </span>
          <span class="lite-domain-toggle">−</span>
        </button>
        <div class="lite-domain-body">
          ${items.map(r => renderRiskCard(r, { open: false, compact: false }).outerHTML).join('')}
        </div>
      </div>
    `;
  }
  html += '</div>';
  return html;
}
```

Wire toggle handler:
```javascript
function wireDomainToggles() {
  const groups = risksListEl.querySelectorAll('.lite-domain-group');
  for (const g of groups) {
    const head = g.querySelector('.lite-domain-head');
    head.addEventListener('click', () => {
      const isOpen = head.getAttribute('aria-expanded') === 'true';
      head.setAttribute('aria-expanded', !isOpen);
      g.dataset.open = isOpen ? '0' : '1';
      head.querySelector('.lite-domain-toggle').textContent = isOpen ? '+' : '−';
    });
  }
}
```

Replace the current `risksListEl.innerHTML = risks.map(...).join('')` with grouping.

**Task 4.2:** Add CSS in `hover_lite.css`

Add styles for `.lite-domain-groups`, `.lite-domain-group`, `.lite-domain-head`, `.lite-domain-body`, `.lite-domain-sev-dot`:

```css
/* Domain groups */
.lite-domain-groups {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.lite-domain-group {
  border: 1px solid var(--border);
  border-radius: 6px;
  overflow: hidden;
}

.lite-domain-group[data-open="0"] .lite-domain-body {
  display: none;
}

.lite-domain-head {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  padding: 8px 10px;
  background: var(--surface-2);
  border: none;
  color: var(--text);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  text-align: left;
  transition: background 0.15s;
}

.lite-domain-head:hover {
  background: var(--surface-3);
}

.lite-domain-icon {
  flex: 0 0 auto;
  color: var(--text-dim);
}

.lite-domain-name {
  flex: 0 0 auto;
}

.lite-domain-count {
  margin-left: auto;
  color: var(--text-dim);
  font-weight: 500;
}

.lite-domain-sev {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--text-dim);
}

.lite-domain-sev-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  display: inline-block;
}

.lite-domain-sev-dot[data-sev="high"] { background: var(--high-ink); }
.lite-domain-sev-dot[data-sev="medium"] { background: var(--med-ink); }
.lite-domain-sev-dot[data-sev="low"] { background: var(--low-ink); }

.lite-domain-toggle {
  flex: 0 0 auto;
  width: 16px;
  text-align: center;
  color: var(--text-dim);
}

.lite-domain-body {
  border-top: 1px solid var(--border);
}

.lite-domain-body .lite-rc:last-child {
  border-bottom: none;
}
```

## Phase 5 — Cross-file duplicate warnings (1 file: sync.py)

**Task 5.1:** In `backend/sync.py`, after loading all part YAMLs, add cross-file duplicate detection

- Collect all claim titles grouped by domain across all parts
- For each domain, compute pairwise Jaccard for cross-file pairs
- Log warnings for pairs with Jaccard ≥ 0.4

```python
def warn_cross_file_duplicates(parts: list[dict]) -> None:
    """Log warnings for near-duplicate claim titles across part files."""
    from backend.core.title_sim import title_similar
    claims = []  # list of (part_id, file_path, claim_key, title, domain)
    for part in parts:
        part_id = part.get("part_id", "?")
        file_path = part.get("_source_file", "?")
        for claim in part.get("claims", []):
            claims.append((part_id, file_path, claim["claim_key"], claim["title"], claim.get("domain", "")))
    
    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            pi, pj = claims[i], claims[j]
            if pi[4] != pj[4]:  # different domain → skip
                continue
            if pi[0] == pj[0]:  # same part → skip
                continue
            if title_similar(pi[3], pj[3]):
                log.warning(
                    "Cross-file dup: %s (%s) ~ %s (%s)  |  %s vs %s",
                    pi[2], pi[1], pj[2], pj[1], pi[3], pj[3],
                )
```

Call this after loading all parts, before the DB sync loop.

## Phase 6 — Testing

**Task 6.1:** Backend tests for dedup
- Test `_deduplicate_results()` with: empty, single item, no matches, one merge, multi-domain
- Test `_merge_cluster()` strength/severity preservation
- Test with 6 timing belt claims → ~2 groups
- Location: `backend/tests/test_resolver_dedup.py` or add to existing test file

**Task 6.2:** Manual frontend verification
- Load extension, open panel on a listing with many risks
- Verify domain sections appear
- Verify collapse/expand works
- Verify count badges are correct
- Verify individual risk cards render correctly inside sections

## Dependencies

```
Phase 1 ──→ Phase 2 ──→ Phase 3
                │
                └────────→ Phase 4 (parallel with Phase 3)
                
Phase 5 ──→ independent, can run anytime after Phase 1

Phase 6 ──→ after Phase 2 and Phase 4
```
