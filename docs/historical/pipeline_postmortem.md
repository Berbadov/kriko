> TL;DR (archived 2026-09-25): Postmortem of the first full pipeline run (Renault Megane 4,
67 sources, 3 runs, 1 auto-verified claim). Six failure modes with fixes: generic-gate
perspective, text-slice bug, no candidate persistence, vanishing review claims, Tier-A
dependency, verbatim-quote false precision. Priority fixes table at the end.

# Knowledge Pipeline — What Went Wrong & How to Improve

First full end-to-end run: Renault Megane 4, 67 sources, 3 pipeline runs, 1 new auto-verified claim.

---

## What went wrong

### 1. gate_generic had the wrong perspective

Asked "is this true of many cars?" — rejected exactly the non-obvious things a first-time diesel buyer needs (EGR clogging, DPF city-driving issues, K9K injector fuel sensitivity).
**Fix applied:** reframed to "would a first-time buyer already know this?" Only trivially obvious claims rejected now.

### 2. promote.py was checking the wrong text slice (the text slicing bug)

Extraction used `doc.text[:6000]`; the gate checked `source.text[:2000]` — quotes past char 2000 failed support and scored 0, silently killing most of run 1 (cost a full second run to diagnose).
**Fix applied:** gates check `claim.quote` directly.

### 3. No candidate persistence — every bug fix cost a full re-run

Every gate fix cost a full re-run: re-fetch 67 pages + 169 extraction LLM calls. Extraction output never saved.
**Fix needed:** cache candidates to `knowledge/cache/{make}_{model}_{gen}_candidates.json`; add `--skip-extraction` to `process.py`.

### 4. review and held claims vanish after every run

8 genuine Megane 4 issues reached `review` (severity=high forces sign-off) but were only printed to terminal and lost — found three times at token cost.
**Fix needed:** write `review` claims to YAML as `status: review`; humans promote by hand-editing one line per claim.

### 5. Tier weights created a single-point dependency on Tier A sources

Tier A = 1.0 (auto-verifies alone); Tier C = 0.34 (needs 3 sources at old 1.0 threshold, 2 at 0.5). Most claims had exactly one Tier C source — stuck below threshold. Only gaga.ba (Tier A) verified; 66 pages contributed nothing for math reasons, not content reasons.
**Fix needed:** tier weight should set displayed confidence, not block DB entry; persist review claims and let humans promote.

### 6. The verbatim quote requirement creates false precision

LLM-copying verbatim spans from trafilatura-stripped forum/blog HTML yields hallucinated or over-short quotes; gate_support then checks quote-against-itself.
**Fix needed:** quote = source pointer, not grounding anchor; gate_support checks title + rationale vs source text.

---

## What worked

- **gate_generic** kills truly generic claims once reframed.
- **Dedup (Jaccard)** collapsed 169 → 130 candidates, zero LLM calls.
- **gate_variant** works after loosening to engine-code mentions (K9K, H5H) vs exact variant IDs.
- **Mistral ministral-8b** with `response_format: json_object`: valid JSON every call, no structured-output failures post-LangChain.
- **Tier A source (gaga.ba)** produced the one verified claim (detailed injector write-up).
- **Docker volume mount**: YAML updates live without image rebuild.

---

## Priority fixes for next session

| Priority | Fix | Effort |
|----------|-----|--------|
| High | Write `review` claims to YAML as `status: review` | 1 hour |
| High | Cache extracted candidates to JSON, add `--skip-extraction` | 2 hours |
| Medium | gate_support checks rationale vs source text, not quote vs quote | 30 min |
| Medium | Manually promote the 8 review claims from this run | 10 min |
| Low | Tier weights influence confidence display only, not promotion gate | planning |
