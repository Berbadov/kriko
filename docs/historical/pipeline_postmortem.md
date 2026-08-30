# Knowledge Pipeline — What Went Wrong & How to Improve

First full end-to-end run: Renault Megane 4, 67 sources, 3 pipeline runs, 1 new auto-verified claim.

---

## What went wrong

### 1. gate_generic had the wrong perspective

The gate asked "is this true of many cars?" A mechanic says yes to EGR clogging, DPF
city-driving issues, injector sensitivity to fuel quality — so the gate rejected them all.

But these are exactly the non-obvious things a first-time diesel buyer needs to know before
purchasing. They are not a mechanic. They don't know diesels need highway runs to regenerate
the DPF. They don't know K9K injectors are sensitive to water in the fuel. That's the whole
point of Kriko.

**Fix applied:** Reframed gate_generic from "is this true of many cars?" to "would a
first-time buyer already know this without being told?" Only trivially obvious claims are
rejected now (oil needs changing, brakes wear over time).

---

### 2. promote.py was checking the wrong text slice (the text slicing bug)

Extraction used `doc.text[:6000]` to pull quotes from source pages. The gate then checked
`source.text[:2000]` — if the extracted quote lived past character 2000 in the page, the gate
never saw it, failed the support check, and scored 0.

This silently killed most of run 1. It required a full second run to diagnose.

**Fix applied:** Gates now check `claim.quote` directly — the verbatim span the extractor
already identified — instead of re-slicing the raw page text.

---

### 3. No candidate persistence — every bug fix cost a full re-run

Each time a gate bug was found and fixed, we had to re-fetch all 67 pages, re-call the
extraction LLM 169 times, then re-run all four gates on all claims. Extraction output was
never saved to disk between runs.

**Fix needed:** After extraction, cache candidates to a JSON file
(`knowledge/cache/{make}_{model}_{gen}_candidates.json`). Gate re-runs then cost zero
extraction tokens and zero web fetches. Add a `--skip-extraction` flag to `process.py`.

---

### 4. review and held claims vanish after every run

8 claims cleared all gates, accumulated score, and are genuine Megane 4 reliability issues.
They went to `review` because severity=high forces human sign-off. They were never written
anywhere — just printed to the terminal and lost.

We burned tokens finding them three times.

**Fix needed:** Write `review` claims to the YAML as `status: review`. The human promotes
them to `verified` by hand editing — one line change per claim. This is the actual intended
workflow for high-severity claims and it currently doesn't exist.

---

### 5. Tier weights created a single-point dependency on Tier A sources

Tier A = 1.0 (auto-verifies alone). Tier C = 0.34 (needs 3 independent sources to reach
old 1.0 threshold, 2 to reach current 0.5 threshold). In practice most claims had exactly
one Tier C source — permanently stuck below threshold.

Only one page (gaga.ba, Tier A) produced a verified claim. 66 other pages contributed nothing
to the verified set — not because the content was bad, but because the math didn't add up.

A claim confirmed by two independent Turkish mechanics' forums is more trustworthy than one
specialist remanufacturer page. The tier system reflects source type but shouldn't be the
sole gate to production.

**Fix needed:** The tier weight should influence confidence displayed to the user, not be a
hard blocker on whether a claim enters the DB at all. Persist review claims and let humans
promote them — that's the right trust boundary for high-stakes claims.

---

### 6. The verbatim quote requirement creates false precision

Asking an LLM to copy a verbatim quote from trafilatura-stripped HTML produces either
hallucinated spans or over-short quotes that don't survive the gate_support check. We are
processing forum posts and Turkish repair blogs, not academic papers.

gate_support then checks the quote against itself — circular and fragile.

**Fix needed:** Treat the quote field as a source pointer ("this is roughly where the
evidence is") not a hard grounding anchor. gate_support should check claim title + rationale
against the source text, not quote vs quote.

---

## What worked

- **gate_generic** correctly killed truly generic claims ("brakes wear", "fuel filter needs
  replacing") once reframed correctly.
- **Dedup (Jaccard)** collapsed 169 candidates to 130 cleanly with no LLM calls.
- **gate_variant** correctly identified model-specific claims after the prompt was loosened
  to accept engine-code-level mentions (K9K, H5H) rather than requiring exact variant IDs.
- **Mistral ministral-8b** returned valid JSON on every call with `response_format:
  json_object`. No structured output failures after switching from LangChain.
- **Tier A source (gaga.ba)** produced the one verified claim — the injector failure write-up
  was detailed, specific, and correctly quoted.
- **Docker volume mount** now means YAML updates are live without rebuilding the image.

---

## Priority fixes for next session

| Priority | Fix | Effort |
|----------|-----|--------|
| High | Write `review` claims to YAML as `status: review` | 1 hour |
| High | Cache extracted candidates to JSON, add `--skip-extraction` | 2 hours |
| Medium | gate_support checks rationale vs source text, not quote vs quote | 30 min |
| Medium | Manually promote the 8 review claims from this run | 10 min |
| Low | Tier weights influence confidence display only, not promotion gate | planning |
