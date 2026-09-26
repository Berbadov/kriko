# Kriko — Design Flaw Assessment (2026-07-04)

Why the project felt disappointing after months of work, and why claims
mismatched across similar component models. (After `matcher.py`,
`resolver.py`, `promote.py`, the part YAMLs,
`docs/historical/pipeline_postmortem.md`.)
**Headline:** one root flaw in different clothes. Serving is well designed;
the pipeline never got an "aboutness" check.

## Flaw 1 (root cause): a claim's identity is "which search found it", not "which component it describes"

Per-part-file research: survivors land in `dq381.yaml` as `dq381_...`
**regardless of subject** (*"DQ200 dry-clutch / hydraulic / sensor
failure"* as DQ381 — a wet-clutch box showing another gearbox's profile).
`promote.py`'s full-page code-token bypass lets any "DQ381"-mentioning article
carry DQ200 claims past `gate_variant`; `_mentions_other_brand` vetoes only
*other manufacturers*.
**Fix:** same-manufacturer **sibling veto/reroute** (DQ200/DQ250/DQ381;
DC4/DW5; EA211/EA288/EA888; K9K/H4D/H5D/H5H) — non-target sibling in claim text
vetoes the bypass or reroutes — plus one-time YAML cleanup.

## Flaw 2: parts are split on the wrong axis (power tune, not engineering identity)

Tune-split IDs (`ea888_220`/`_230`, `k9k_85`/`_100`), but *"nobody writes
K9K_85 on a forum"*: same engine researched twice (double tokens, drifting
duplicates) while real splits (dry/wet clutch, EA888 Gen2 vs Gen3, K9K DPF) go
unmodelled.
**Fix:** one file per *source-nameable engineering identity* (`ea888_gen3`,
`dq200`); variant applicability at the fitment layer.

## Flaw 3: aliases actively cause the contamination

`dq200.yaml`'s `[7-speed DSG, 7DCT, DSG7]` also describes the DQ381;
`dc4.yaml`'s `EDC` also fits the DW5. Aliases feed queries **and** matching
but are unique-ish only for search — ambiguous exactly across mismatching
siblings.
**Fix:** two-tier aliases — *discriminative* (`DQ200`, `0AM`) for attribution
vs *search-only* (`7-speed DSG`) never used to attribute.

## Flaw 4: contamination flows straight to buyers

`resolver.py` served `review`/`held` as "reported". Nearly all rows are
`review, promoted_by: pending_human, confidence: 0.6` — the sign-off never
happens, so live output's bar is "ministral-8b gate + bypasses".
**Fix:** enforce human promotion (fast review CLI) or stop serving unreviewed
`review`/`held` at high severity.

## Flaw 5: whack-a-mole patches around a judge that is too weak

`promote.py` history (hallucination → bypass → over-admit → brand veto →
model-mention bypass → …) rebuilds mechanical discrimination as regex around a
model that can't do it.
**Fix:** one stronger-model attribution call per claim (not per gate), sibling
registry + descriptions in-prompt — replaces three bypasses, two vetoes.

## Flaw 6 (product): the pipeline keeps what sources mention, not what Kriko exists to show

Generic OBD items and inspection-caught issues ship live, ungated by the
product principle (config-specific, mileage-predictable, high-consequence,
"due unless the ad proves otherwise").
**Fix:** "inspection-covers-it" filter + mileage-gating on `known_issue`.

## Observability gap: /analyze results cannot be investigated without a browser

`AnalysisLog` keeps IDs/counts only; no driving listing context ("why shown"
unanswerable); no raw request (no replay); hand-opened DB only.
**Fix:** full request meta + response JSON per analysis (JSON column or
`logs/analyses.jsonl`); browser-free read path (`GET /debug/analyses?limit=20`,
`python -m ops.reports.analyses --last 20`); **replay** through
`match_variant` + `resolve_claims` with diff; then agent audits of recent
analyses, no browser needed.

## General assessment

**Keep:** strict never-guessing `matcher.py`; `resolver.py`'s fail-open vs
fail-closed split; DB-only serving, no request-path LLM; postmortem
discipline; honest UX ("no data ≠ problem-free").
**Weaknesses:** no end-to-end serving regression harness (gold covers
extraction, not output); thin manual coverage (3 models, TR; Flaw 2 doubles
per-model cost); post-hoc cleanup scripts (`purge_forums.py`,
`purge_german.py`, `purge_invalid_severity.py`,
`downgrade_unsourced_claims.py`, `normalize_domains.py`,
`find_cross_file_duplicates.py`) — fold into `validate_part_yaml.py`; TR/EN
mixing in served text (`translate_claims.py` as pass, not invariant).

| # | Fix | Impact | Effort |
|---|---|--------|--------|
| 1 | Sibling veto/reroute + YAML cleanup | Kills live wrong-component claims | Small |
| 2 | Full /analyze logging + read path + replay | Makes every other fix verifiable | Small |
| 3 | Merge tune files into engineering-code files | Halves research cost, kills dupes | Medium |
| 4 | Two-tier aliases | Prevents recontamination | Small |
| 5 | Enforce promotion or stop serving unreviewed high-severity | Restores trust boundary | Small |
| 6 | Product-principle gate (inspection filter, mileage gating) | Signal vs noise — the product | Medium |
| 7 | Stronger-model attribution replacing bypass stack | Ends whack-a-mole | Medium |
