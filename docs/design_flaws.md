# Kriko — Design Flaw Assessment (2026-07-04)

An honest audit of why the project feels disappointing/incomplete after months of work,
and why claims mismatch between similar-yet-different component models. Written after
reading `matcher.py`, `resolver.py`, `promote.py`, the part YAMLs, and
`pipeline_postmortem.md`.

**Headline:** the failures are mostly ONE root design flaw expressing itself in
different places — not months of wasted work. The serving plane (matcher/resolver)
is genuinely well designed; the knowledge pipeline never got an "aboutness" check.

---

## Flaw 1 (root cause): a claim's identity is "which search found it", not "which component it describes"

The pipeline researches *per part file*. When `auto.py` runs for DQ381, every claim
that survives the gates is written into `dq381.yaml` with a `dq381_...` claim key —
**regardless of what component the claim is actually about**. Attribution is inherited
from the search context and never verified against the claim text.

Live evidence in `backend/data/parts/transmission/dq381.yaml`:

- line 9: *"DQ200 dry-clutch pressure circuit failure (accumulator/pump)"* — filed as DQ381
- line 34: *"DQ200 hydraulic pressure failure"*
- line 57: *"DQ200 transmission pressure sensor failure"*

The DQ381 is a wet-clutch 7-speed. The DQ200's dry-clutch and hydraulic-accumulator
failures are precisely the problems the DQ381 **does not have**. A Golf R buyer is shown
the failure profile of a different gearbox.

**Why existing guards miss it:** the deterministic code-token bypass in `promote.py`
checks the *full source page* for a code match (deliberately, to survive clipped
quotes). Any DSG comparison article mentions "DQ381" somewhere, so every claim on that
page — including DQ200-specific ones — rides the bypass past `gate_variant`. The
cross-brand guard (`_mentions_other_brand`) patched this exact mechanism, but only for
*other manufacturers*. DQ200 vs DQ381 is same-brand, so it sails through.

**Fix:** a same-manufacturer **sibling-component veto/reroute**. Maintain a registry of
sibling codes per family (DQ200/DQ250/DQ381; DC4/DW5; EA211/EA288/EA888; K9K/H4D/H5D/H5H).
If the claim's *own text* names a sibling code that isn't the target part, veto the
bypass — or better, reroute the claim to the sibling's file instead of dropping it.
Plus a one-time cleanup pass over existing YAMLs with the same rule.

---

## Flaw 2: parts are split on the wrong axis (power tune, not engineering identity)

Part IDs split by power tune (`ea888_220`, `ea888_230`, `k9k_85`, `k9k_100`) — but as
`search_templates.py`'s own comment admits, *"nobody writes K9K_85 on a forum."*
Sources cannot distinguish these, so:

- The **same physical engine is researched twice**, paying double tokens for
  near-duplicate claim sets that then drift apart (`ea888_220` leads with oil
  consumption, `ea888_230` with tensioner failure — both are true of both).
  `find_cross_file_duplicates.py` existing at all is the symptom.
- Meanwhile the splits that **actually matter mechanically** — dry vs wet clutch,
  EA888 Gen2 vs Gen3 (piston-ring oil consumption is Gen2/early-Gen3-specific),
  K9K DPF vs non-DPF — are not modelled at all.

**Fix:** one part file per *real engineering identity* (what sources can name:
`ea888_gen3`, `dq200`), with per-variant applicability handled at the fitment layer,
not by duplicating research.

---

## Flaw 3: aliases actively cause the contamination

`dq200.yaml` lists `known_also_as: [7-speed DSG, 7DCT, DSG7]` — the DQ381 is *also* a
7-speed DSG. `dc4.yaml` lists `EDC` — so does the DW5. Aliases feed search queries
**and** identity matching, but they are only unique-ish for search; as attribution
evidence they are ambiguous across exactly the sibling sets where mismatches occur.

**Fix:** two-tier aliases — *discriminative* (safe for attribution: `DQ200`, `0AM`)
vs *search-only* (`7-speed DSG`, `2.0 TSI`), never used to attribute a claim.

---

## Flaw 4: contamination flows straight to buyers

`resolver.py` serves `review` and `held` claims as "reported"
(`SERVABLE_STATUSES = ("verified", "review", "held")`). Nearly everything in the part
files is `status: review, promoted_by: pending_human, confidence: 0.6` — the human
sign-off step the postmortem designed never actually happens, so the effective quality
bar on live output is "survived a ministral-8b gate plus deterministic bypasses".
Combined with Flaw 1, wrong-gearbox claims are servable today.

**Fix:** either enforce the human-promotion step (a fast review CLI over pending
claims) or stop serving unreviewed `review`/`held` claims at high severity.

---

## Flaw 5: whack-a-mole patches around a judge that is too weak

The comment history in `promote.py` tells the story: ministral-8b hallucinates → add
code-token bypass → bypass over-admits → add brand veto → add model-mention bypass →
(next: sibling veto…). Each patch is locally sound, but the judgment task is being
incrementally rebuilt as regex around a model that cannot do it. `gate_variant` is a
fine-grained mechanical-discrimination question ("is this claim about *this*
gearbox?") given to the weakest model with impoverished context.

**Fix (longer term):** one stronger-model attribution call per claim (not per gate),
with the sibling-code registry and part descriptions in the prompt — likely replaces
three bypasses and two vetoes.

---

## Flaw 6 (product): the pipeline keeps what sources mention, not what Kriko exists to show

Already acknowledged in `CLAUDE.md`: live output includes generic OBD/warning-light
items and things a standard pre-purchase inspection catches anyway. The product
principle (config-specific, mileage-predictable, high-consequence, "due unless the ad
proves otherwise") is written down but not enforced by any gate. An
"inspection-already-covers-this" filter and mileage-gating on `known_issue` claims are
open work.

---

## Observability gap: /analyze results cannot be investigated without a browser

There is an `AnalysisLog` DB table (`_log_analysis` in `backend/api/main.py`), but it
is investigation-hostile:

- It stores only claim **IDs** and counts — not titles, strengths, severities, or the
  summary actually shown. Reconstructing "what did the buyer see" needs manual joins.
- It does not record the **listing context that drove gating** (mileage_km, age,
  equipment tags, description keywords) — so "why was this maintenance claim shown/hidden"
  is unanswerable after the fact.
- It does not store the raw request payload, so a bad match cannot be **replayed**
  against a fixed pipeline.
- There is no way to read it except opening the DB by hand.

**Fix (planned):**
1. Log the **full request meta + full response JSON** per analysis — either a JSON
   column on `AnalysisLog` or an append-only JSONL file (`logs/analyses.jsonl`).
2. Add a read path that doesn't need a browser or DB client:
   `GET /debug/analyses?limit=20` (last N analyses, full payloads) and/or a small CLI
   (`python -m ops.reports.analyses --last 20 --model golf`).
3. Add a **replay** tool: feed a logged request back through `match_variant` +
   `resolve_claims` after a fix and diff the output.
4. Once payloads are logged, **agents can audit them directly**: scan recent analyses
   for sibling-code contamination (a DQ200-titled risk served for a DQ381 variant),
   ambiguous matches that should have narrowed, `inconsistent_listing` spikes, and
   claims that violate the product principle — no browser in the loop.

---

## General assessment

**What is genuinely good — keep it:**
- `matcher.py`: strict, never guesses; plausibility gate + narrowing-never-to-empty is
  the right shape. Input sanitisers show real-world hardening (the 96130-hp case).
- `resolver.py`: the fail-open (missing data) vs fail-closed (confirmed equipment
  mismatch) distinction is exactly right and well documented.
- Serving plane is DB-only — no LLM on the request path. Correct architecture.
- The postmortem discipline (`pipeline_postmortem.md`) is rare and valuable; most of
  its findings were acted on.
- Honest UX copy: "no data ≠ problem-free", unavailable ≠ clean.

**Structural weaknesses beyond the flaws above:**
- **No end-to-end regression harness**: there is no fixture of real listings with
  expected served-claims output, so every pipeline change risks silent regressions in
  what buyers see. The gold set (`knowledge/gold/`) covers extraction, not serving.
- **Coverage is thin and manual**: 3 models, TR market, each added by a hand-driven
  pipeline run. There is no scale story yet — that's acceptable for now, but Flaw 2's
  duplicate research cost makes each new model ~2× more expensive than it should be.
- **Cleanup scripts are accumulating instead of pipeline fixes**: `purge_forums.py`,
  `purge_german.py`, `purge_invalid_severity.py`, `downgrade_unsourced_claims.py`,
  `normalize_domains.py`, `find_cross_file_duplicates.py` — each is a post-hoc mop for
  something the pipeline should not have emitted. Fold their invariants into
  `validate_part_yaml.py` as hard checks so bad output fails at write time.
- **Turkish/English mixing in served text** (`ea888_230`: "Hidrolik tensioner
  failure") — translation/normalization is a separate half-finished pass
  (`translate_claims.py`) rather than a pipeline invariant.

**Priority order:**

| # | Fix | Impact | Effort |
|---|-----|--------|--------|
| 1 | Sibling-code veto/reroute in promote.py + cleanup pass on existing YAMLs | Kills live wrong-component claims | Small |
| 2 | Log full /analyze payloads + debug read path + replay tool | Makes every other fix verifiable | Small |
| 3 | Merge power-tune part files into per-engineering-code files | Halves research cost, kills cross-file dupes | Medium |
| 4 | Two-tier aliases (attribution-safe vs search-only) | Prevents recontamination | Small |
| 5 | Enforce human promotion or stop serving unreviewed high-severity | Restores the designed trust boundary | Small |
| 6 | Product-principle gate (inspection-covers-it filter, mileage gating) | Signal vs noise — the actual product | Medium |
| 7 | Stronger-model attribution call replacing the bypass stack | Ends the whack-a-mole | Medium |
