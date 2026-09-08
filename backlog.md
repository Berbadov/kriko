# Kriko — Backlog

Prioritized open work. Read `CLAUDE.md` (product, scalability, automation principles)
before picking anything up. When an item is finished, move it to `done.md` with the
date and commit hash.

- **P0** — actively hurting buyers or blocking everything else
- **P1** — the next round of high-leverage work
- **P2** — real, but can wait

Evidence for many items comes from production logs: `logs/analyses.jsonl`
(`python -m ops.reports.analyses --last 20`).

---

## Goals (2026-08)

**G1 — Quality over quantity.** A buyer sees at most ~8 risks, and they are the
*general chronics*: config-specific, high-consequence, multi-source-corroborated issues.
Today a DSG Golf gets 39–86 cards; nobody reads 39 cards.

**G2 — Cut pipeline cost per car by ~10×.** Classification spend must be budgeted,
cached, and reported. **(Landed 2026-07-22 — B1 closed.)**

**G3 — No silent coverage holes.** If a car is automatic, its gearbox chronics must show.
Ad-vs-catalog contradictions and empty part files must be *visible* (coverage_state,
coverage report), never a quiet zero.

**G4 — One trunk.** **(Done 2026-07-22 — all branches merged, worktrees pruned.)**

**G5 — Fully automated pipeline. Zero human-in-the-loop** *(new 2026-08-03)*.
Extraction and scraping run unattended; nothing in the data path — evidence, catalog
rows, gates, sources — may wait for human verification, spot-checks, or sign-off.
One-time *policy* decisions are allowed (market coverage, source licensing); per-car
and per-datum review is not. Where a value cannot be derived automatically, the system
**fails open** (no claim, no guess) and logs the gap; the log drives the next automated
pass, never a human TODO. This retires HUMAN DECISION #6/#7 (B17/B11) and all
"manual audit/spot-check" backlog steps.

**Cross-cutting rule — systemic only** *(2026-08-03; replaces the patch-and-mechanism
pairing)*. The catalog grows to thousands of models, so *no per-model fixes exist*.
Every fix ships as a mechanism that runs for all cars (coverage report, contradiction
surfacing, auto-remediation). Per-model manual steps (research runs, YAML audits,
spot-checks) are cancelled, not deferred — see B19, which absorbs B2/B3.

---

## Goal G6 — Kriko becomes a product knowledge engine *(new 2026-08-26)*

Kriko stops being a car product and becomes an open-source, local-first knowledge
engine for any manufactured product. Cars become pack #1. Design and phases:
`~/.claude/plans/let-s-go-with-the-eager-torvalds.md` (to be moved into
`docs/superpowers/specs/` when Phase 1 lands).

The pivot rests on one change: **slots become rows, not columns.** `variants`
assumes every subject has a make, a model, an engine code and a displacement —
already false for an EV, hopelessly false for a cordless drill with no components.
Two contributors modelling a category differently must still produce mergeable
databases; columns cannot union, rows can.

Locked: subject/attribute/value rows in SQLite; `pack_id` on every row; no central
authority (contradicting claims coexist, ranking happens at read time); packs
authored as a directory and shipped as one `.kpack` file; Postgres and Docker
deleted; research pluggable between the $0 agent/MCP path and an Exa/Tavily+LLM
path; every install is both reader and author; language is a row attribute;
monorepo with `packs/` beside the engine.

### Current delivery constraint — web-first minimal slice
The next milestone is a usable local browser workflow, not another CLI-only path. Every
operation must be operable and inspectable from the dashboard with a visible result,
error, and durable status. The minimal slice covers: health and installed pack state;
pack build/install/revision/enable/disable/uninstall; generic product/listing analysis;
identity, coverage, flags, ranked claims, reasons, and sources; subject browsing;
coverage gaps; recent activity; and explicit empty/unknown results.

Research execution and the remaining pipeline separation stay behind browser-visible
job state rather than requiring a terminal, MCP client, or manual data-path step.

### B29 — Phase 1: the `kriko/` core `[G6]` **(LANDED 2026-08-26)**
`kriko/store/{schema.sql,ids.py,db.py,packstore.py}` + 28 tests. WAL on; two
databases, never merged. `test_kriko_core_never_imports_a_domain_layer` in
`ops/tests/test_repo_invariants.py` is the mechanical guarantee that adding a
category stays a data-only change.

Corrected while writing the tests: identical facts from two packs do **not**
collapse to one row. `pack_id` is in every primary key, so each pack keeps its
own row with the same content hash — otherwise uninstalling one pack would
delete a fact the other still asserts. Dedup is a read-time `GROUP BY` on the
agreeing hash, never a storage-time merge.

### B30 — Phase 2: pack format and the drill pack `[G6]` **(LANDED 2026-08-26)**
`kriko/pack/{manifest,build}.py` + `packs/drill/` + 24 tests. Authoring a pack is
data-only: YAML in, SQLite out, no Python. The builder validates strictly — a
claim pointing at a nonexistent subject, or an attribute using an undeclared
term, fails the build rather than shipping a row nobody would see.

The drill pack is deliberately **synthetic** (`synthetic = true`, every URL on
the reserved `example.invalid` domain, pinned by a test). It exists to falsify a
car-shaped format, not to inform: no engine/fuel/displacement, wear measured in
`charge_cycles`/`usage_hours`, and one product with zero relations. Rebuild it
from real sources once the researcher interface lands in Phase 5.

### B31 — Phase 3: generic lookup `[G6]` **(LANDED 2026-08-26)**
`kriko/lookup/{conditions,match,rank,query}.py` + 52 tests. Replaces
`matcher.py` (226) + `resolver.py` (650) with no car knowledge in either.
Read-time trust; `stance='refutes'` halves rank and shows the rebuttal.

The condition evaluator answers in **three** states, not two: `met`, `unmet`,
`unknown`. Unknown is where an engine starts lying — an unstated mileage makes a
"fails after 150k" claim neither true nor false, so it is served and downranked
with the reason attached, per the fail-open rule in G5.

`test_packs_that_disagree_on_identity_keys_still_both_answer` covers the design's
riskiest property (two authors, different identity keys, different hashes, must
still union). `test_core_is_domain_free.py` walks kriko/'s AST for car vocabulary
in executable positions and carries its own negative test.

### B32 — Phase 4: cars pack + parity `[G6]` **(LANDED 2026-08-26)**
`packs/cars/` — 699 claims, 26 variants, 21 parts, 89 relations, 676 conditions,
725 evidence rows. `parity_golden.jsonl` captured (98 rows) while both engines
still exist. Two gates green over 98 real listings: wherever the old engine
matched, the new one resolves the identical car; and all 2,121 old claim
instances are represented.

Three deliberate divergences, each asserted by a test rather than assumed:
status became rank (**closes B26**), year windows are soft (**B9**), and part
attribution is stricter — the old sync served DC4 gearbox faults to a diesel
Mégane out of the *h5f petrol engine's* part file, a car not fitted with that
engine. Five titles listed in `KNOWN_ATTRIBUTION_FIXES`; the list must shrink to
nothing when the catalog is refiled.

Found while measuring: compatibility gates must be suppressed for any attribute
the part is fitted *across* (a gearbox shared by petrol and diesel spans both
fuels, so a text signal naming a petrol engine describes the source, not the
part). Derived from fitment, never an exception list.

### B33 — Phases 5–6: interfaces, then delete the old path `[G6]`
CLI + web (finishing `ops/hub/web.py`, which lands B28) + MCP on the new core;
extension becomes a cars-pack site adapter. Then `backend/`, `knowledge/catalog/`,
`ops/swap.py`, `ops/process.py` go.

- [x] Phases 5a–5d **(landed 2026-08-26)** — CLI, MCP, the two research planes,
      the local dashboard, and the pack-declared site adapter.
- [x] **Phase 6a landed 2026-08-27** (`e5d7951`): `backend/` and `deploy/` deleted,
      `ops/{hub,mcp,reports,swap}` gone, the car catalog moved to
      `packs/cars/data/`, the coverage report moved to `packs/cars/coverage.py`
      and now derives servability from the pack manifest. Layering re-derived
      from a column to a fan and re-enforced in `test_repo_invariants.py`, with
      a ratchet that keeps `backend/` deleted. Suite 534 -> 535, 3m -> 18s.
- [x] **Phase 6 docs landed 2026-08-27** — `README.md` and `CLAUDE.md` rewritten
      for the pack architecture (every command in the README verified to run).
- [x] **Phase 6b landed 2026-08-29** (`f038df9`) — generic ledger/extraction primitives moved
      to `kriko/ledger/` and `kriko/extract/`; car catalog, sources, parts, fitment,
      acquisition, export, resolution, and research policy moved to
      `packs/cars/pipeline/`; `knowledge/` is deleted. Pack vocabulary and gate
      terms are data, not engine constants. `app/pipeline/` owns orchestration.
- [x] **Phase 6c landed 2026-08-27** — the Chrome extension is on the new
      protocol and the client keeps no site knowledge of its own.
      `content.js` reports the page's own label/value pairs and interprets
      nothing (697 -> 426 lines; `mapTurkishKeys`, `mapTechnicalDetails`,
      `parseMakeModelFromTitle` and its hardcoded make list are gone);
      `background.js` POSTs that to `/api/analyze` on 8787 and asks
      `/api/adapters` which sites are worth scraping at all; the panel renders
      the resolved identity rather than its own reading of the page. JS tests
      14 -> 36, with `background.js` covered for the first time. Verified end
      to end against the real cars pack: both captured fixtures resolve to a
      full identity with **zero unmapped labels** and 8 ranked claims.

      Five bugs the rewire found, each fixed as a mechanism:
      - **`packs/cars` could not be built.** Phase 6a moved
        `trust/source_tiers.yaml` in from `backend/` unchanged and the builder
        expected a different shape; nothing noticed, because every suite built
        its own fixture and the one pack that ships was never built in CI.
        `test_every_pack_in_the_repo_builds_and_is_not_empty` is the mechanism
        (it also catches the empty-build case, since a pack may ship its own
        `build.py`), and an unreadable trust file is now a build error rather
        than a pack that silently trusts nothing.
      - **A near-miss label answered for a rule.** "Yakıt Tüketimi" contains
        "yakıt", so consumption could be read as the fuel type. Labels now
        match exact-before-loose, and `ignore_labels` is a real blocklist
        rather than a reporting filter.
      - **Turkish "İ" broke every accented label.** It casefolds to "i" plus a
        combining dot, so `İlan No` never matched `ilan no` and the adapter
        carried hand-kept transliterations. Both ends now strip combining
        marks (letters, including "ı", are untouched).
      - **The title fallback needed a make list.** Replaced by `vocabulary`:
        an adapter rule says "find a known value of this attribute in the
        title" and `kriko/` resolves it from the packs' own `is_identity`
        rows — no list, in any language, and it works for a category nobody
        has written yet.
      - **The panel footer would have read "unknown" forever** (B15's
        deploy-staleness guard, pointed at a `build` field the new payload has
        no reason to carry). Re-pointed at what a reader now needs: which
        pack, at which version, answered.

      New adapter vocabulary, all closed and all interpreted server-side:
      `from` (a labelled rule's text fallback), `vocabulary`, `segment`.
      `/api/analyze` also returns `packs` and `context_units`; `/api/adapters`
      returns `labels`.

- [ ] **Phase 6c follow-up — the manifest is the last hardcoded site list.**
      `extension_ui/manifest.json` still names `*.sahibinden.com` in
      `content_scripts.matches` and `host_permissions`, so installing a pack
      for a second listing site does nothing until someone edits it. Every
      other layer is now adapter-driven. The fix is
      `chrome.scripting.registerContentScripts` over the adapters' `site`
      values, but MV3 cannot inject into a host it has no permission for, so
      it needs `optional_host_permissions` plus a user grant — a UX decision,
      not a mechanism gap, which is why it is filed rather than done.
- [x] Architecture and usage docs rewritten for the new `app/`, `kriko/`,
      `packs/`, and `extension/` layout; old interface references removed from
      active documentation. Older product-quality work is re-filed against the
      new core where still applicable.

**HUMAN DECISION #8 — resolved 2026-08-29.** Choose the long-term split: generic
ledger/extraction lives in `kriko/ledger/` and `kriko/extract/`; car-specific
acquisition, catalog, parts, fitment, export, and research policy live in
`packs/cars/pipeline/`. `app/pipeline/` is orchestration only. This leaves a
pack-supplied seam for future categories without making the core car-aware.

---

## P0

### B16 — Catalog swap: serve the ledger export instead of legacy part YAMLs `[G1][G2]`
The ledger export (knowledge/ledger_export/, 568 claims) is acceptance-ready per the
parity report; the serving-gate schema gap is closed. Remaining:
- [x] Export rewritten to the part-dict schema with serving-gate fields grounded at
      export. **Done 2026-08-02.** Regenerated 2026-08-03 from the ledger (19 parts,
      536 claims — the checked-in copy had gone stale; the fresh export covers
      dq200/dq250/dq381/ea211/ea888/k9k) and each file now carries
      `legacy_part_ids` (which legacy power-split files it supersedes —
      pipeline-derived, no hand list).
- [x] **Swap mechanism landed 2026-08-03** (`ops/swap.py`):
      `plan` derives the legacy→merged fitment remap mechanically
      (power-collapse rule via the export's `legacy_part_ids`), classifies every
      legacy file (superseded/retained), counts fitment edits; `apply` writes the
      export into `parts/<type>/`, deletes superseded power-split files,
      overwrites non-split ids in place, rewrites fitment axes (revertible, and
      default off the real catalog — runs on a copy unless `--in-place`);
      `check` is the **automated acceptance gate** (no human sign-off):
      (a) parity: every legacy claim absent from the export must be attributable
      to a named gate — "never extracted/ingested/no matching evidence" are
      LOST and fail; (b) serving: the 43-listing baseline replayed against the
      current catalog AND the post-swap catalog on fresh DBs — the swap's own
      delta, with a monotonicity rule (a listing that matches today must still
      match after the swap); (c) coverage: post-swap must not add findings.
      Tests: `knowledge/tests/test_ledger_swap.py`.
- [x] **Swap LANDED 2026-08-03** — `apply --in-place` replaced
      `backend/data/parts/` with the export (25 legacy files superseded,
      dw5/dw6 retained-then-covered, fitment remapped k9k_110→k9k etc.).
      Acceptance gate **PASS** under the $0 gate policy: 0 lost claims
      (URL-less legacy claims = unverifiable provenance; pending/mixed
      clusters = adjudicated-or-in-the-ledger; YouTube URLs = retry-owned by
      the remediate loop), 0 match-loss serving regressions (43 listings
      replayed, current-vs-post-swap), coverage 18→9. Serving DB re-syncs on
      next deploy. Two swap-caught data bugs fixed: `code_family_extra`
      (sibling aliases, r9m/M9R) now preserved by `apply` from superseded
      legacy files, and `component_part_meta` copies it on power-merge; the
      resolver's `_best_in_cluster` no longer mutates persisted ORM claims
      (replay-determinism bug). Legacy judge.py/promote.py/purge_*/translate
      + their tests retired (14 files, 75 tests) — `ops.process`'s
      promote steps now raise with a pointer to the ledger path.
- [ ] **Post-swap maintenance**: re-run `swap check` after any re-export;
      `python -m ops.ledger_run remediate` keeps coverage + parity
      gaps closed (default $0/import-only mode).

### B11 — Emissions/SCR values: derive or fail open — no sign-off `[G3][G5]`
The mechanism landed 2026-08-02 (`Variant.emissions`/`aftertreatment` +
`_scr_compatible`/`_default_aftertreatment` in `backend/sync.py`, `write_variants.py`
support, `test_scr_gate.py`). The old HUMAN DECISION #7 sign-off is cancelled under G5:
- [x] Hand-typed Megane 4 values removed (2026-08-03) — all variants fail open
      again (no SCR grounding), which is strictly safer than the unverified
      `scr` value on `megane4_k9k_110_edc` for 2016–18 cars.
- [x] Year-split row support landed in `write_variants.py` (2026-08-03) —
      `emissions` may be a list of year-bounded segments; each segment emits its
      own variant row (`{id}__{emissions}` suffix), aftertreatment derived per
      segment, windows validated against the trim. Tests:
      `knowledge/tests/test_write_variants_emissions.py`.
- [x] Coverage report lists diesel variants with no emissions value
      (2026-08-03) — new `variant_no_emissions` finding kind
      (`ops/reports/coverage.py`); the gap is visible, never a quiet wrong
      value.
- [ ] Derive emissions values from sources via the ledger for Clio 5 + Golf 7 +
      Megane 4 (evidence path, then `write_variants.py` regen). Until then,
      fail-open stands and the coverage report shows exactly which variants
      lack data.

### B19 — Auto-remediation loop: coverage gaps fix themselves `[G3][G5]` *(absorbs B2/B3)*
The detection mechanisms exist: B7's coverage report (`zero_claim_part`,
`auto_variant_no_tx_part`, `ops/reports/coverage.py`) and B6's ad-vs-catalog
contradiction surfacing. The former B2/B3 manual steps are cancelled; this loop
replaces them:
- [x] **Driver landed 2026-08-03** — `python -m ops.ledger_run remediate`
      (`ops/remediate.py`): turns every part-level finding
      (zero_claim/missing part, auto-variant-without-tx-part) into an unattended
      acquire → extract → resolve → cluster → verdict → export pass. Budget-capped
      (`--max-usd`), resumable (existing stage guarantees), `--dry-run` prints the
      plan, empty plan = no spend. Every run appends `logs/remediation.jsonl`
      (findings, parts, rows gained, spend). Findings carry `part_id`/`axis`
      metadata for the loop (`coverage.Finding`); `orphan_part` and
      `variant_no_emissions` are deliberately not part-driven research.
      Tests: `knowledge/tests/test_ledger_remediate.py`, coverage metadata tests.
- [ ] First live instances the loop must fix: `dw5`/`dw6` (empty EDC
      transmission parts) + the other 7 empty Megane 4 parts — a scheduled
      remediate run with EXA/DeepSeek credentials resolves them; the B16 swap
      then makes the export the serving catalog and completes the loop.
- [ ] "Manual only in TR" notes in `volkswagen_golf_7.yaml` (esp. 1.6 TDI DSG) and
      Clio 5 diesel rows: no manual audit; contradiction + coverage signals drive any
      regen. (Transmission coverage is already enforced by B6/B7 checks.)

### B17 — Official recall feeds: DROPPED `[G3]` *(HUMAN DECISION #6 resolved 2026-08-03)*
All official sources are dropped — TR SGM, EU Safety Gate, and NHTSA. TR SGM was
already blocked by an anti-bot challenge; the decision now removes the whole class.
The 50 ingested EU Safety Gate rows stay in `ledger.db` as history, but:
- [ ] Retire `knowledge/ledger/feeds/` ingesters and their `run.py feeds` wiring
      (remove, or leave dormant — they must not run).
- [ ] Recall coverage ends here unless a non-official automated source is later
      onboarded (B18-adjacent); no human recall checking exists.

---

## P1

### B34 — Re-wire or drop the two orphaned gate capabilities from the deleted `gates.py` `[G2]`
This pass (`2a88372`) removed `packs/cars/pipeline/agent/gates.py` after re-wiring it —
`check_evidence`'s vocabulary became `packs/cars/vocabulary/gates.yaml` rows, its
thresholds became `limits` rows, and its rule shapes became
`kriko.gates.structural_reasons`. Two of the old module's three public functions,
plus one supporting mechanism, were **not** ported and now have no caller anywhere
(so nothing running today changed — this is a capability gap, not a live bug):
- `check_document(url, raw_text, target_hint, existing_for_target)` — rejected
  blocked/forum domains, rejected snippets-instead-of-article-text, and enforced a
  server-side per-part research budget.
- `duplicate_of(title, known_titles)` plus `DUPLICATE_THRESHOLD` — title-level dedupe
  against claims already on file for the same target.
- The advisory-warning mechanism (`WEAK_TIERS` + `resolve_tier` integration) that
  warned on weak source tiers and on a missing `inspection_advice`. `resolve_tier`
  itself still exists in `packs/cars/pipeline/sources/tiers.py` but now has no caller
  outside its own module.
- `title_has_dtc_code` (a raw diagnostic-trouble-code shape check on the title) —
  a fourth lost rule, omitted from this inventory until the final review of this
  pass caught it. It still lives in `packs/cars/pipeline/stoplists.py` with no
  caller in the current write path (see `docs/USAGE.md`'s "Removed, not currently
  enforced").

All three are fully recoverable — the deleted file existed at commit `367e62f`.
Decide: re-wire document-level gating and title dedupe into the current agent research
path (`app/mcp_server.py`'s `submit_findings`), or delete `resolve_tier` too if the
project decides document-level gating isn't worth the research path's complexity.

### B35 — Gate calibration: false-rejection rate when a claim carries no `component` anchor `[G2]`
`packs/cars/tests/test_gate_calibration.py` (not `packs/cars/pipeline/tests/...` — that
path was a mislabel) measures the write-path gate's false-rejection rate across every
claim in `packs/cars/data/parts/**/*.yaml`. Two numbers, remeasured 2026-08-30 after the
`noise`-scoping fix and the `has_anchor` threading through `gate_reason` (final review
of this pass, finding 1/2):
- **Anchored** (claim has a `component` field): **1.29%** (9/699) — asserted in the
  test, ceiling 5% in aggregate, plus a per-kind bound per rule (added by the same fix).
  Was 3.29% (23/699) before the fix — the drop is `noise` losing its false rejections of
  rationale text mentioning a warning light while describing a real chronic.
- **Unanchored** (no `component`): **21.46%** (150/699) — measured and reported by the
  test, deliberately *not* asserted (would make the suite depend on catalog content
  that is expected to keep changing). Was 23.03% (161/699) before the fix.

`app/mcp_server.py`'s `submit_findings` docstring was updated this pass to tell agents
to always send `component`, which is why the anchored number is the one that should
apply in practice going forward. The unanchored number is still worth tracking: it
says roughly a fifth of catalog-shaped claims carry no configuration anchor in their
own text, which reads as a statement about **catalog quality** as much as about the
gate. Revisit if the unanchored rate moves a lot, or if agents keep omitting
`component` despite the docstring. Not filed as a bug — no fix is proposed here.

### B36 — Product-principle question: does a bare mileage figure earn the specificity escape? `[G3]` **(HUMAN DECISION #9 — open)**
Under both the original write-path gate and the one restored by this pass (`2a88372`),
a bare mileage figure in a claim's title satisfies the "config-specific" escape that
waives the ekspertiz-routine (`covered`) rejection — so *"Brake pad wear at 60,000 km"*
surfaces while a bare *"Brake pad wear"* is dropped. `CLAUDE.md`'s product principle
explicitly names brake-pad wear as routine pre-purchase-inspection ground that Kriko
should not surface ("Anything the standard pre-purchase mechanic inspection already
catches as routine — fluid levels/leaks, **brake-pad wear**, injector bench tests,
compression"). Read literally, that principle says neither phrasing should surface —
a mileage figure alone doesn't make routine wear config-specific in the sense the
principle means (engine/gearbox/fuel/market variant), it just adds a number.

This is **pre-existing behaviour**, not introduced by the current pass — both the
original gate (before this pass) and the restored one preserve it identically. It is a
**taste decision for the project owner**, not a refactoring decision: does "mileage
present in the title" count as the kind of specificity the product principle asks for,
or does it need to be tightened so routine-wear items still get dropped even with a
mileage figure attached? Whichever way this is decided, the fix is a one-line change
to `kriko/gates.py`'s specificity check (or to `packs/cars/vocabulary/gates.yaml`'s
`covered` rows) plus a calibration-test update (B35) to confirm the rejection rate
doesn't regress.

### B26 — Settle the 696 `status: review` claims deterministically `[G1][G5]` **(CLOSED 2026-08-26 by B32 — status became rank, not a gate)**
The claim inspector (done.md B25) made the size of this visible: **696 of ~699
catalog claims sit at `status: review`**, i.e. the pipeline never settles a
claim and the serving tier is doing that judgement implicitly. The mechanism
now exists — `knowledge/agent/gates.py` gives a deterministic keep/drop verdict
with reasons, and the hub records where a human disagrees with it
(`ops/hub/claim_signals.jsonl`). Remaining:
- [ ] Run the gate over the catalog as a pipeline step that writes a settled
      status/`value_tier`, not a hub button (no human in the data path).
- [ ] Feed `claim_signals.jsonl` disagreements into the gate's calibration test
      (the 10/699 rejection rate is pinned; a signal that contradicts it is a
      failing case to add).
- [ ] Fold into B5's ranking: settle first, then budget the survivors.

### B27 — Golf 8's gearbox code is unresearched `[G3]` *(new 2026-08-19; test case, not a fix target)*
`golf8_ea211evo2_150_auto` carries `transmission_code: 7_speed_dsg`, which
names three different gearboxes. The doctor fails it open (`draft: true`, kept
out of serving) and reports it as `invalid_code` needing research. Per the
generalization principle this is a **test case for the remediation loop**
(B19), not a car to hand-fix: the loop must be able to take an `invalid_code`
finding and drive a research pass that resolves it.
- [ ] Teach `ops/remediate.py` to consume doctor findings
      (`invalid_code`, `draft_variant`) alongside coverage findings.

### B5 — Per-part claim budget: keep the chronics, archive the tail `[G1]`
896 claims across part files for 3 models (~300/model) is the volume problem at its
source. Rank claims within each part by consequence × independent-source count ×
specificity; keep the top ~15 servable, move the tail to a non-synced archive section.
Corroboration count *is* the "general chronic" signal. Respect the product principle
test in `CLAUDE.md` ("would the standard inspection catch this anyway?"). Fully
automated — ranking is a deterministic pipeline step, no review.

### B9 — Year-window near-miss policy: ADOPTED `[G3][G5]`
A 2024 Megane 1.3 TCe listing no_matched ("No renault megane petrol for 2024" —
`year_to: 2023`). Policy (no further decision): a listing outside the known window
still matches the variant, carries a "year outside known window" note in the
response, and logs a demand signal for the catalog. Windows may later be extended
from TR-market data — also automatically, via the demand miner (B10).

### B20 — kriko-hub: clickable pipeline dashboard `[G2][G5]`
**Landed 2026-08-04** (`ops/hub/`, USAGE §4d). **Web edition is the
live one**: `ops/hub/web.py` (fastapi+uvicorn, 127.0.0.1:8787) — six
browser tabs (Overview/Parts/Sources/Run/Ledger/Coverage) over the
test-pinned `metrics.py`, run buttons spawning `ops.ledger_run`
(`--max-usd` caps, streamed output, stop), 1s polling. The DearPyGui app
(`app.py`) is deprecated — GL rendering on WSLg was unusable (GLX missing,
scaling breakage, per-second rebuild stalls swallowing clicks); the web
version renders in the host browser instead. `run.py` gained
`verdict --import-only` for the $0 button.

### B21 — MCP server + kriko_research agent: subscription-LLM engine, $0 research `[G2][G5]`
**Landed 2026-08-04** (`ops/mcp/server.py`, USAGE §4e, opencode.json →
`mcp.kriko`, `.opencode/agents/kriko_research.md`). 13 stdio tools; the full
agent loop tested end-to-end: `add_document` (hash-idempotent) →
`add_evidence` (extractor_version=1, deduped) → `run_pipeline_pass`
(resolve/cluster/import-verdicts/export, logged `model=agent, usd=0`).
Import-verdict predicate generalized `{0}` → `⊆ {0,1}`; LLM-eligible clusters
still queue paid verdicts only for extractor-version-2 evidence.
`pip install mcp>=1.0,<2.0` (2.0 dropped FastMCP). **Closed by B23** (harness
wiring + model entry point); see `done.md`.

### B23 — Agent-driven model onboarding: no hand-edited trim table `[G2][G3][G5]`
**Landed 2026-08-16.** B21's agent could only start from a coverage finding that
already named a `part_id`, so a car with **no scaffold** was unreachable, and
scaffolding one meant a human editing `TR_MARKET_TRIMS` in
`knowledge/catalog/write_variants.py` — the exact hand-enumerated per-model list
the scalability rule forbids. Now the researcher agent supplies the lineup:

- `write_variants.run(trims=...)` injection; `TR_MARKET_TRIMS` demoted to the CLI
  fallback (row content verified byte-identical for every onboarded car).
- `validate_trims()` — deterministic structural checks only. An unsourced figure
  is **not** an error: the row is written `draft: true`, sync skips it, coverage
  raises `draft_variant`. Fail open, never guess.
- MCP `onboard_model()` (work list: scaffold state, draft rows, part codes tagged
  missing/zero_claim/has_claims) and `submit_trims()` (validate → write variants +
  fitment → record lineup sources as `spec` documents). 15 tools total.
- `add_evidence()` verifies the quote is actually present in the submitted
  document (casefold + whitespace-normalized) and **rejects** fabricated
  citations. Previously `quote_grounded` was `bool(quote)` — any string passed.
- Harnesses wired: `.mcp.json` (Claude Code) + `.claude/agents/kriko_research.md`
  alongside opencode's; Codex/Cline snippets in USAGE §4e. The server owns
  validation, so hosts are interchangeable and none can bypass the gates.
- Agent loop is now **one model per pass** (was one part).

- **Top-down picker** (2026-08-16): make → model → generation → run, no typing.
  Makes/models come from the demand queue (`ops.reports.demand` over
  `logs/analyses.jsonl`), `not_onboarded` first — traffic-derived, never a
  maintained list. Generation is researched in a phase-1 agent pass
  (`submit_generations` / `list_generations`, lineups in
  `knowledge/catalog/generations/`), which also resolves scraped display names
  (`vw_cc_1_4_tsi` → `passat_cc`) via `canonical_model` + aliases.

- **Task/harness/model picker + command preview** (2026-08-16): both agent task
  forms as buttons, harness and LLM model as dropdowns, and the exact argv shown
  before it runs (`POST /api/agent-preview` shares the run endpoints' argv
  builder, so preview and execution cannot drift). Model lists come from
  `opencode models`, never shipped here.
  **Found doing this:** the hub passes `.env` to the harness, so opencode
  reported 406 models — 380 of them pay-per-token providers unlocked by
  `DEEPSEEK_API_KEY`/`MISTRAL_API_KEY`/`OPENROUTER_API_KEY`. One dropdown pick
  would have silently spent API credits and broken the $0 premise. Now split
  into flat-rate vs `⚠ pay-per-token` optgroups with a preview warning; the
  split derives from the `*_API_KEY` names in `.env`.

- Hub **Models tab** (2026-08-16): onboarding control room — catalog rollup,
  per-model work list, draft rows with their missing figures, `POST /api/onboard`
  spawning opencode/Claude Code, and a live activity feed read off the *ledger*
  (harness-independent, shows per-row quote grounding). Shared `model_state`
  module backs both the MCP tool and the UI so they cannot drift.

- [x] First live run happened (VW Golf 8) and **failed quality**: the lineup
      came back as marketing trims, with a description in place of a gearbox
      code. Fixed as a mechanism, not a patch — see done.md B24 (identity
      module, catalog doctor, server-side product-principle gates, derived
      research brief). Re-run it through the gated path to confirm
      `SUM(usd) WHERE model='agent'` stays 0.
- [ ] Re-onboard already-catalogued cars through the agent path, then delete their
      `TR_MARKET_TRIMS` entries (the fallback keeps them working until then).

### B22 — MCP-driven extraction: budget-capped paid tools on the MCP server `[G2][G5]` *(deprioritized 2026-08-16)*
**Deprioritized by B23:** the point of the agent path is the $0 plane — a
subscription harness doing the research is what makes onboarding cheap, so adding
paid tools to the MCP surface works against it. Revisit only if subscription
throughput (rate limits, session ceilings) proves insufficient in practice. The
analysis below stands if that happens.

`ops/mcp/server.py` (B21) is the **$0 plane by construction**: every write tool is
deterministic or import-only, `add_evidence` writes `extractor_version=1` rows that skip
the paid extractor, and `run_pipeline_pass` / `run_remediate_import_only` never spend
tokens. The paid engine (chunked DeepSeek extraction, batched verdicts) is reachable only
from the CLI (`python -m ops.ledger_run extract|verdict|remediate --max-usd`) and
the hub Run buttons. There is **no plan for an MCP path to the paid stages** — this item
is that decision + mechanism. Two options:

- **Option A — one wrapper tool (recommended first step).** `kriko_remediate(max_usd,
  dry_run=False)` calls the B19 loop unchanged (coverage findings → acquire → extract →
  resolve → cluster → verdict → export; budget-capped, resumable, appends
  `logs/remediation.jsonl`). Thin surface, reuses the tested driver; an agent closes
  coverage gaps end-to-end at a capped cost. Limitation: coverage-driven — the agent
  cannot say "extract *these* documents".
- **Option B — stage tools.** `kriko_extract(max_usd)` + paid `kriko_verdict(max_usd)`
  (verdicts only needed for the `extractor_version=2` evidence the extractor creates —
  `extractor_version=1` rows already flow through deterministic import verdicts). Makes
  extraction doc-driven: the agent commissions the real grounded extractor on documents
  it found, instead of hand-writing evidence rows. Literal "MCP-driven extraction"; more
  surface and per-stage budget bookkeeping. Natural follow-up on A — both stages already
  exist as `run.py` commands.

Mechanism constraints (G5 automation + generalization): budget is a **mandatory** tool
parameter enforced server-side by the same `costs` charging the CLI uses (no unbudgeted
spend, ever); paid agent runs log to `runs` (`model=agent`) so the hub cost panel stays
honest; MCP tools call the same `run.py` entrypoints as the CLI — one code path, no
second pipeline. Applies to all parts; no per-model logic.

- [ ] Decide A vs B (recommendation: A first; B only if doc-driven extraction proves valuable).
- [ ] Wire the tool(s) to the existing `run.py` entrypoints with `--max-usd` enforced server-side.
- [ ] `kriko_research.md` contract: "never invoke paid stages" → "never exceed the passed budget".
- [ ] Hub cost panel shows agent-paid spend (runs already carry `model=agent`; verify `usd > 0` renders).
- [ ] Tests in `test_mcp_server.py`: budget-capped paid tool with a mocked LLM stage — cap honored, spend logged, dry-run free.

---

## P2

### B37 — Long-function readability residue: eight (now more) functions over 90 lines `[G5]`
Tasks 10–11 of the 2026-08-29 simplification pass split the two functions the spec
scoped (457 → 65 lines, 300 → 28 lines). The plan named eight more, all outside that
scope, with line counts measured when the plan was written: `validate_part()` (194),
`process.run()` (153), `process.run_part()` (152), `ledger_run.main()` (144),
`export_all()` (142), `submit_findings()` (128), `lookup()` (119), `build_report()`
(114).

Re-measured 2026-08-30 with the same AST walk (`ast.FunctionDef`/`AsyncFunctionDef`,
excluding `/tests/`), those eight are all still present — `submit_findings()` grew to
**155 lines** (a later fix in this same pass lengthened its docstring to document the
`component` anchor requirement, B35) — and the same walk with the plan's >80-line
threshold now also catches nine more that were not named in the plan (`build_report()`
above is the one already named — these are new to this list):
`packs/cars/build.py:_conditions_from()` (91),
`packs/cars/pipeline/parts/search_templates.py:templates_for_part()` (98),
`packs/cars/pipeline/catalog/discover.py:_match_specs_to_variants()` (91) and
`discover()` (93), `packs/cars/pipeline/catalog/write_variants.py:run()` (92),
`packs/cars/pipeline/catalog/doctor.py:repair()` (93),
`packs/cars/pipeline/ledger/parity.py:explain_only_old()` (100),
`app/web/routers/analyze.py:analyze()` (90), `kriko/store/packstore.py:install()` (91).

None of this is a correctness bug — it's readability. Splitting seventeen unrelated
functions with no behaviour test behind most of them is a different, larger piece of
work than the simplification pass funded, and doing it without tests first would be
trading a readability problem for a regression risk. If this is picked up, write
characterization tests per function before splitting (test-driven-development skill),
and do not attempt all seventeen in one pass — group by module/owner instead.

### B38 — Measure how much the offline ledger's low-value gate widened `[G2]`
`packs/cars/pipeline/ledger/extraction.py:_low_value_reason` (`extract_document`'s
`gate_reason` callback) now routes through the full `kriko.gates.gate_reason`, which
means the offline ledger's chunk-extraction path flags evidence under `covered` and
`ambiguous` too — two rule kinds the old `_deterministic_low_value_reason` this
replaced never applied there (it only ever caught `noise`-shaped warning-light
language at extraction time; `covered`/`ambiguous` were write-path-only checks before
this pass). Flagged evidence is excluded from clustering
(`kriko/ledger/cluster.py:41`), so a false-positive `covered`/`ambiguous` flag here
can never reach export — this is a silent widening of what evidence gets dropped
before a human or agent ever sees it, not a live bug, and nothing currently measures
its rate.

Found during the final review of the 2026-08-29 simplification pass (finding 4);
filed rather than fixed per that review's own instruction not to fix findings 4/8 in
the same wave. Next step: instrument or backfill a measurement of how often
`covered`/`ambiguous` (as opposed to `noise`) fire on this path across a ledger run,
then decide whether the widening is wanted — it may well be (evidence that reads as
routine-and-unspecific is plausibly not worth clustering either), but that is a
decision to make with the number in hand, not by default.

### B39 — The research brief still tells agents to call tools that don't exist `[G2]`
`kriko/research/agent.py:53` (`research_brief`'s generated prompt) still tells
research agents to call `add_document` then `add_evidence` — neither tool exists;
the real (and only) write path is `submit_findings`. It also lists only
`quote`/`title`/`domain`/`severity` as the fields to send, omitting `document_text`
(without which `submit_findings` refuses every finding — see the grounding check at
`app/mcp_server.py`) and `component` (the anchor field that waives the specificity/
generic/ambiguous escapes, per B34/finding 2 of the 2026-08-29 pass's final review).

Two other surfaces carrying the same contract were already corrected in that pass —
`submit_findings`' own docstring and `.claude/agents/kriko_research.md` — this third
one (the brief the engine itself generates and hands to an agent at the start of a
research session) was missed. An agent following this brief literally would call
tools that raise `AttributeError`/tool-not-found, then likely improvise a shape that
`submit_findings` refuses for missing `document_text`. Fix: rewrite the brief's
tool-call example to name `submit_findings` with its real field list
(`title`, `rationale`, `quote`, `document_text`, `source_url`, `component`, plus
`domain`/`severity`).

### B40 — `packs/cars/pipeline/ledger/export.py`'s `errors`/`path` may be read unbound `[G5]`
Same bug family as the `component_part_meta` fix in the 2026-08-31 decontamination
pass (`2f0d061`, filed in `done.md`): `errors` and `path` inside the `for comp, claims
in sorted(by_component.items()):` loop of the export function around lines 438-455
are only assigned inside the `for _attempt in range(2):` sub-loop, then read after it
at `if errors or not kept:`. `range(2)` always runs at least once in the reachable
path today, so this has not fired — but that is exactly the shape that hid the
`component_part_meta` bug for however long it went unguarded (a branch that happens
to always run, verified by nothing). Deliberately left alone rather than
guessed-and-fixed in this pass: the fix belongs with a test that actually forces the
sub-loop to be skippable (or proves it can't be), the same way `2f0d061` rebuilt
`test_component_part_meta_power_collapsed` to force its branch by construction
rather than by accident of current data.

### B41 — Coverage loss: `test_adapters.py` no longer covers "two mutually plausible
values, identical digit format" `[G5]`
Pre-pivot, `test_range_bounds_disambiguate_identical_digit_patterns` fed
`"1.461 Nm"` and `"148.000"` — two independently plausible readings (a real torque, a
real mileage) sharing one dot-grouped digit pattern, disambiguated only by which
field's declared range believed which. The 2026-08-31 decontamination pass (Task 7)
moved this fixture to `packs/drill/`'s vocabulary; drill's magnitude profile (torque
~1-200, charge cycles ~0-2000) has no pair of dot-grouped integers that are each
independently plausible for a *different* field — any value plausible for one is
implausible for the other. Round 2 (`11c8b6f`) replaced it with a real but weaker
demonstration: `"1.200"` fed to both fields, believed for `charge_cycles`, correctly
absent from `max_torque_nm` (an accept/reject split on one shared value, not two
independently-valid readings). If the engine's adapter-parsing test suite ever needs
this exact case back, it needs either a fixture category whose two fields' plausible
ranges genuinely overlap in one digit-grouped format, or a synthetic (non-pack)
SPEC built for the purpose rather than borrowed from an installed pack's real
vocabulary.

### B42 — `pip install .` (non-editable) is unverified `[G5]`
`pyproject.toml`, added in the 2026-08-31 decontamination-and-packaging pass, has no
`package-data` or `MANIFEST.in` entry. `src/kriko/store/schema.sql` and
`src/app/web/static/*` are non-`.py` files the serving path needs at runtime; without
an explicit data-files declaration, a built wheel would plausibly ship without them
while `pip install -e .`'s editable `.pth` (which points straight at the source tree)
would still find them and hide the gap. Every command this pass verified went through
the editable install only. Needs: build a real wheel (`python -m build`), install it
into a clean venv with no source checkout on the path, and run the server/build
commands against that install.

### B43 — The prose gate is a worklist, not a proof `[G5]`
`src/kriko/tests/test_core_is_domain_free.py`'s `_prose_offences` check (added
2026-08-31) is real and load-bearing, but its guarantee is narrower than it sounds:
green means "no un-allowlisted `PROSE_BANNED` word appears in a `kriko/` docstring or
comment," not "no category leakage." It cannot catch a leak phrased without any
banned word (an explanation that names a mechanism by *behaviour* specific to one
category rather than by vocabulary), and every `ALLOWED_PROSE` entry is a judgment
call about whether an example "genuinely clarifies," not a mechanically checked
property. Worth restating for whoever runs the next pass: a green gate narrows the
search, it does not end it. No action item — this is a documentation gap in what the
gate proves, not a bug in the gate.

### B28 — Split `ops/hub/web.py` into routers `[G5]` **(SUPERSEDED 2026-08-26 by B33 — `apps/web/` ships the router split on the new core; the blocker was import-time path constants, now a Settings value passed through an app factory)**
`web.py` is 831 lines and ~28 endpoints after the 2026-08-22 helper extraction
(1151 originally; `textfmt.py`/`agents.py`/`claimview.py` took the pure helpers).
Splitting the endpoints themselves is blocked on a test-coupling problem, not a
code problem:

Endpoints read `DATA_DIR`, `RUNS_LOG`, `CLAIM_SIGNAL_LOG` and `AGENT_RUN_LOG`
from module scope, and `ops/tests/test_hub_web.py` patches them with
`monkeypatch.setattr(web, "DATA_DIR", tmp_path)`. A function resolves globals
from the module it was **defined** in, so moving `/api/models` to a
`routes_catalog.py` detaches it from the patch — it would read the real
`backend/data/` instead of the fixture and still return 200. A test that passes
while testing nothing is worse than a red one.

Doing this properly means moving the config globals to an `ops/hub/config.py`
and repointing ~8 `monkeypatch` targets from `web` to that module — mechanically
simple, arguably better tests (patch config, not the app module), but it is a
test change, so it was held back from the behaviour-preserving pass.

Acceptance: route table (path + methods) diffed identical before/after — the
2026-08-22 pass used exactly this check and it caught a real over-capture.

### B13 — Remaining design-flaw work (`docs/design_flaws.md`)
- Flaw 5: judge too weak → whack-a-mole patches. The ledger's verdict stage is now on
  `main` (B1, 2026-07-22) — closes for the pipeline; the *served* catalog inherits the
  fix at the B16 catalog swap.
- Flaw 6: pipeline keeps what sources mention, not what Kriko exists to show. The
  deterministic product-value gate is on `main`, dropping ~230 claims in the export;
  closes at B16 + B5.

### B14 — Documentation audit: docs must match the code
2026-07-16 pass fixed the worst drift. Remaining (all one-time doc work, allowed
under G5):
- [ ] Verify every INTERNALS.md mechanism section against current code — it predates
      the part-centric flow in places.
- [ ] USAGE.md §5/§7 still document the model-centric legacy mode prominently;
      restructure around the part-centric flow.
- [ ] Decide whether `docs/historical/handover.md` earns a rewrite or deletion (B12 landed).

### B18 — Source adapter ToS decisions: wire recalls/specialists/forums into the pipeline `[G2]`
Three source adapters exist (`knowledge/sources/recalls.py`, `specialists.py`,
`forums.py`) with working `fetch()` methods, blocked on **HUMAN DECISION #5** —
the only remaining human decision, and the only allowed kind under G5: a one-time
licensing/policy gate, not per-car review. Once confirmed, wiring into
`knowledge/ledger/acquire.py` (with a `--sources` flag) is fully automated. Note:
with B17, the official recalls adapter is retired — specialists/forums remain.

### B44 — No LICENSE file `[G5]` **(HUMAN DECISION #10 — open)**
There is no `LICENSE` file anywhere in the repo, and no licence is named in
`README.md`, `CLAUDE.md`, or `pyproject.toml`. `README.md` calls Kriko "open," but
with no licence granted, default copyright applies — all rights reserved — which is
the opposite of what "open" implies to a reader on GitHub. Per the 2026-08-31 branch
review that caught this: an earlier ruling had promised to file this decision and did
not — filing it here for real. One-time policy decision, same
category as B18's source-ToS call: which licence (if any) to publish under, and
whether `pyproject.toml`'s classifiers/`license` field should be updated to match.
Not a mechanism gap — nothing to automate here.

### B45 — `sources.published_at` is written by nobody
The ledger has no publication-date extractor, so the tree reports it always empty.
Derive it from page metadata during ingest, or drop the column.

### B46 — `evidence.independent` is `1` on all 719 rows; nothing ever computes independence
Until it does, "independent sources" means "distinct sources", and the health view
says so. Deriving it (same domain, same syndicated text, same author) is the real fix.

### B47 — no producer emits `stance = 'refutes'`, so the sharpest signal in the health view has zero live hits
The verdict step already sees contradicting evidence within a cluster; it should
record the rebuttal rather than discarding it.

### B48 — feed observed weakness back into `relevance()`
Deliberately out of scope for the knowledge-tree observability pass (spec
non-goal), but a claim with one forum source ranking beside one with three
bulletins is a ranking question, not only a reporting one.

### B49 — `rank.py`'s `score_sources` and `tree.py` disagree about what "independent" means
`src/kriko/lookup/rank.py:score_sources` increments its `independent` counter once
per *evidence row*, with no deduplication by source URL. Two quotes extracted from
one page therefore count as two independent sources and earn the claim a
corroboration step on the serving path buyers actually see. `kriko/lookup/tree.py`
does dedupe (`len({e.url for e in supporting if e.url and e.independent})`), so the
health view and the ranking now disagree on the same claim. Fix `rank.py` to
dedupe by URL, and add a test asserting the two agree.

### B50 — URL-less sources count as zero sources in the health view
`tree.py`'s `supporting_sources`/`independent_sources` dedupe on `e.url` and
filter `if e.url`, so a source with no URL contributes to neither count. The
schema does not require one: `source_type` includes `manual|structured|dataset`,
`ids.source_id` falls back to hashing the quote text when there is no URL, and
`packs/cars/build.py` happily accepts a quote-only source. Three scanned
service bulletins with no URLs would report `independent_sources=0` and rank
as maximally uncorroborated even though three genuinely independent sources
back the claim. Nothing has caught this yet because nothing has to: 0 of the
193 live sources have an empty `url`. Fix by deduping on a source identity
that falls back to the quote hash (`ids.source_id`'s own logic) instead of
`url` directly.

### B51 — `lang` is hardcoded `"en"` in `tree.py`, unlike `/api/query`
`_nodes()` takes a `lang` parameter but neither `GET /api/health/weakest` /
`GET /api/health/subject/{id}` nor the `subject_health`/`weakest_claims` MCP
tools expose it — every caller gets `lang="en"`. The store holds 699 `en` and
699 `tr` `claim_text` rows, so a pack shipping only `tr` claims yields
`title=''` on every health row: blank table cells, and an evidence `<details>`
with an empty, unclickable summary. Add a `lang` parameter to both surfaces,
matching `/api/query`'s existing precedent, with a fallback to any available
language rather than an empty title when the requested one is missing.

### B52 — The standalone app: signing, and a window nobody has opened `[G6]`
Phases 0–5 landed and **all four installers now build** — see `done.md`
(2026-09-01). What is left is what CI cannot answer:

- **v0.2.4 on Windows did not open at all, and now the shell's own start is
  checked.** The app panicked in `build().expect(..)` before it drew anything:
  `PluginInitialization("updater", "invalid type: null, expected struct
  Config")`. `configure_updater.py` removes `plugins.updater` from a build with
  no signing key — which is every release so far — while `main.rs` registered
  the plugin unconditionally, so the two halves were each correct and together
  fatal. The updater is now registered from `setup` via `AppHandle::plugin`,
  where the failure is a `Result` the shell shrugs at. The *mechanism*, since
  "the installers built" was never evidence that the app opens:
  `packaging/smoke_app.py` launches the bundled shell on the Linux and Windows
  runners and fails on a panic or an early exit.
- **A reader has now run the installer, and it failed.** v0.2.1 on Windows 11
  stopped with "Error opening file for writing: ...\kriko-sidecar.exe", and after
  *Ignore* the app did not open at all. Two causes, both fixed in v0.2.2: a
  leaked sidecar kept its own onefile image mapped (now: `--exit-with-parent`,
  a Windows tree kill, and an NSIS pre-install hook), and `start_engine`
  returned its error into a window that is created hidden, so "no sidecar"
  rendered nowhere (now: every failure path goes through `emit_failure`, which
  shows the window). **Still unconfirmed by a human: the success path** —
  window appears with "Starting Kriko…", the shell reads `KRIKO_PORT`,
  `/api/health` answers, `location.replace` swaps in the dashboard.
- **Nothing is signed.** macOS shows an unidentified-developer warning and
  Windows SmartScreen flags the NSIS installer. Signing needs an Apple
  developer account and an EV certificate — a policy/spend decision, not an
  engineering one (see the human-decisions table).
- **Distribution is wired end to end.** A `v*` tag builds every pack, publishes
  `packs.json` beside the four installers, and the app updates its packs from
  it (*Packs → Check for updates*). The app updates itself the same way, from
  `latest.json` — but self-update is **off until someone generates the minisign
  keypair** and sets `TAURI_SIGNING_PRIVATE_KEY` (secret) and
  `TAURI_SIGNING_PUBLIC_KEY` (variable); see `tauri/README.md`. Until then
  releases ship installers only, which is a deliberate no-op rather than a
  failure.
- **First run offers the index.** ~~The installer carries no pack, so a fresh
  launch answers nothing until the reader presses *Check for updates*.~~ Fixed
  2026-09-03: `Welcome.svelte` is gated on `packs === 0` and offers the index
  by name, installs through the same job path *Packs* uses, and takes a
  `.kpack` file when the index is unreachable. Deliberately *not* bundling
  `cars.kpack`, which would pin knowledge to the binary's release cadence.
  Still unconfirmed by a human on Windows.
- **The extension could not reach the installed app, and now can.** It
  hardcodes `http://127.0.0.1:8787` because a page cannot be told a random
  port, while the sidecar only ever bound an OS-chosen one. The sidecar now
  serves both sockets and `EXTENSION_PORT` is one constant with a guard test.
  Untested against a real Chrome profile and a real Sahibinden page.
- **An agent can now reach the installed app; nobody has driven one yet.**
  *Coverage → Research* still produces a *brief* on the free plane, by design —
  the gathering is done by a coding agent you already pay for. What was missing
  was an address, and that is fixed: the sidecar binary takes `--mcp` and serves
  the MCP stdio server on the same `~/.kriko`, and *Coverage → Connect an agent*
  hands over a per-machine `.mcp.json` block naming the store this window reads.
  Untested with a real harness against a real installer, and there is still no
  in-app *view* of what an agent submitted beyond the ordinary claim screens.
  *(2026-09-07: the skill an agent is handed is now derived from the store —
  identity keys, domains, holdings, gaps, a runnable example, and every reason
  a finding can be refused — so a driven agent no longer has to guess the
  vocabulary. Still nobody has driven one.)*
- **What is already mechanical**: the handshake string must match on both
  sides, no engine vocabulary may appear in Rust, the boot screen must be able
  to render a failure, every data file under `src/` must be declared package
  data, and no tracked path may be unnameable on Windows. All in the ordinary
  pytest suite, no toolchain needed.

### B53 — The desktop shell has no `Cargo.lock`, so no two builds are the same
`tauri/src-tauri/Cargo.lock` is not committed and `tauri-plugin-updater = "2"`
floats, so every CI run resolves whatever crates.io holds that minute. This is
not theoretical: v0.2.1 opened and v0.2.4, four hours later, panicked on a
config both builds shipped identically — the plugin's tolerance for a missing
`plugins.updater` changed underneath an unchanged tree. A lockfile makes a
release reproducible and makes a dependency bump a commit somebody can revert.
Needs a Rust toolchain to generate (`cargo generate-lockfile` in
`tauri/src-tauri/`), which is why it is a row rather than a diff.

Also open from the phase-2 work: the report screen makes weak claim selection
obvious, which is the product principle's open work (B36), not this item's.

---

## P0 — the 1.0.0 release audit *(2026-09-08)*

The full assessment, with the finding-by-finding reasoning, the seven-phase
plan and the six open questions, is the published artifact
`https://claude.ai/code/artifact/b4a4aa7d-18cc-4c2e-b22c-14549587e4c8`
("Kriko 1.0.0 Readiness"). This section is the tracked half — the rows, so
status lives here rather than in a document nobody greps.

**The headline finding, because it frames every row below.** Every automated
gate was green — pytest, vitest, node, svelte-check — and *all four reported
defects passed all of them*. Four defects, four missing categories of gate.
So each row that fixes behaviour also names the gate that was absent, and a
row without one is not finished.

### B54 — Verdict signals split wrong/outdated *(done, see done.md)*

### B55 — The analysis log wrote nothing for two months `[G6]`
**Done 2026-09-08** — `1f3978e`. `observability.log_analysis_jsonl` reported
its failures through `log.warning` into a root logger with no handler, so a
`PermissionError` on every append produced output nowhere. The call site
looked correct, which is what let it survive. Fixed as two rules, in
`src/app/logs.py`: a diagnostic lands beside the store, never in the source
tree; and a path we cannot write is *reported*, not swallowed — `probe()`
returns the reason, `resolve_writable()` falls back rather than refusing to
start, and both the path in use and the rejection reason reach `/api/health`
and the About screen. CLAUDE.md's fail-open rule was never wrong; the missing
half was reporting.

### B56 — Anything a browser visits can drive this app `[G6]`
**Done 2026-09-08** — `ae70e39`. 127.0.0.1 protects the port from the network
and not from the browser: 8787 is a constant published in this repository. An
`Origin` allowlist stops a cross-site GET (`GET /api/focus` is consume-once,
so a page could burn a nudge it cannot even read); a `Host` allowlist stops
DNS rebinding, which no `Origin` check can see. `src/app/web/origins.py`.

### B57 — Four dependency surfaces, none of them locked
`tauri/src-tauri/Cargo.lock` (that is B53), the root `package-lock.json`,
`ui/package-lock.json` and the Python pins. `desktop.yml` should use `npm ci`
for tauri. A release that cannot be rebuilt is not a release, and v0.2.1
opening while v0.2.4 panicked on an identical tree is the evidence.

### B58 — The Console could not be typed in `[G6]`
**Done 2026-09-08** — `1f3978e`. Route changes moved focus to the view
container, which stole it from the prompt the route exists to offer. Fixed by
treating `[autofocus]` as a declaration: a route that autofocuses a control is
taken at its word, and the view container is the fallback. Beats a hardcoded
route-name list and beats racing `document.activeElement`.

### B59 — "Open in App" claimed to raise a window it could not see `[G6]`
**Done 2026-09-08** — `ae70e39`. The response said `raised: true` on any 2xx,
and a 2xx only means the route was recorded. Whether a window came to the
front depends on whether anything is reading the sidecar's stdout — which the
process cannot observe and the shell can declare. `--supervised` on the spawn,
`delivery: "raised" | "no_shell"` on the response.

### B60 — The extension conflated "the app said no" with "there is no app" `[G6]`
**Done 2026-09-08** — `ae70e39`. A 422 (this extension built a route the app
cannot navigate to) was caught by the same `except` as ECONNREFUSED and opened
a tab at the same bad route, hiding a defect in our own code behind a fallback
meant for a missing app.

### B61 — The rail scrolled as a document `[G6]`
**Done 2026-09-08** — `1f3978e`. `grid-template-rows: auto minmax(0, 1fr)
auto` is the whole fix: a track's automatic minimum is its content, so plain
`1fr` refuses to shrink and pushes the overflow back out to the parent. The
rail now clips and only `.rail-nav` scrolls, with auto-hiding shadows done in
four backgrounds (`background-attachment: local, local, scroll, scroll`) — no
script, no ResizeObserver.

### B62 — The rail was plain, and said nothing about state `[G6]`
**Done 2026-09-08** — `1f3978e`. Inline SVG icons for all 16 routes (inline
rather than an icon font, because the app must render with no network and a
font is a box on first paint on the element people navigate with), one sliding
marker rather than fourteen borders that blink, and a stagger on mode switch.
All reduced-motion-safe and token-guarded by `tokens.test.ts`.

### B63 — The updater and `packs.json` URLs 404 for a running app
**Blocked on Q1.** The repository is private, so both point at endpoints a
reader's app cannot reach. Recommendation in the artifact: a releases-only
public mirror.

### B64 — Nothing is signed, so nothing can self-update
**Blocked on Q2.** minisign now (free, and the key must never be lost);
the ~$200–400/yr Windows authenticode certificate can wait.

### B65 — Two more gates the defects walked past `[G6]`
**Done 2026-09-08** — `3343126`. `test_extension_sites.py` derives from the
pack tree that every adapter's site is one the extension actually injects on
(and that the panel's stylesheet reaches it) — the seam where a pack can read
a site the extension never runs on, which the reader sees as "nothing known
about this car". And `smoke_sidecar.py` now asks whether a log can be written
*in the frozen binary*, which is where the paths differ.

### B66 — CI was paused, so the branch had no gate `[G6]`
**Done 2026-09-08** — `3343126`. `ci.yml` runs on push/pull_request again,
with svelte-check added: types were a local-only gate, i.e. one that ran when
someone remembered. The app-first phase's other half stands — it ends when the
reader opens an installer, not when a workflow goes green.

### B67 — The knowledge pipeline has no event spine `[G6]`
**Done 2026-09-08** — `53f0ac0`. The reader's Console showed a job log and nothing about *what the pipeline is
doing*: no stage, no counts, no live view of what was discovered or extracted.
Shipped as `app/web/pipeline.py`: `pipeline_runs` / `pipeline_stages` /
`pipeline_events` in `app.sqlite` (interface state, never the engine's
schema), an `Emitter` the *interface* owns so `kriko/` emits nothing and
learns nothing about the transport, and SSE at `/api/pipeline/stream`. Stages
are Discovery / Extraction / Ingestion / Ledgering. Rows before stream, so a
run killed by a restart is still readable — and marked `interrupted` at
startup rather than left spinning. `NULL` tokens are not `0`: the agent plane
meters nothing and says so. `skipped` is not `done` with zero.

### B68 — The Pipeline route `[G6]`
**Done 2026-09-08** — `9e4a376`. The view over B67: per-stage progress, token counts as they accrue, the
knowledge entries landing and the sources they came from, and transitions
animated because a state change nobody sees is a state change nobody trusts.
Progress is counted in *settled stages*, never interpolated from item counts —
nothing knows how many findings a source will yield, and a bar that moves
backwards is worse than a coarse one. The feed scrolls in its own `role="log"`
region, focusable, because a region a keyboard cannot reach is a region it
cannot read.

### B69 — Adding a listing site is a manual manifest edit `[G6]`
**Done 2026-09-08**. The server learned about a site the moment its adapter
file existed; the extension learned about it when somebody edited
`manifest.json`. `syncSites()` in `background.js` now reads `/api/adapters`,
turns each `site` into exactly one match pattern, and reconciles
`chrome.scripting`'s registrations towards it. The four pieces: *detection* is
the app's answer, never a hostname list in the worker; *synchronisation* reads
back `getRegisteredContentScripts()` and converges, because an MV3 worker's
memory does not survive it; *conflicts* are impossible by construction, ids
being derived (`kriko-site-<host>`); *recovery* is a 30-minute alarm plus
startup and install, and a failed sync keeps every existing registration
rather than tearing the panel down because the app is closed.

The host permission stays a user gesture in the options page — Chrome requires
it and is right to. That is consent for reading a third party's pages, not a
human in the data path. A pack's `site` is validated as a bare hostname, so an
adapter cannot ask for `https://*/*`.

B65's invariant is relaxed, not dropped: a site must be covered by the static
manifest **or** by `optional_host_permissions`, still derived from the pack
tree, and still failing when it is covered by neither.

### B70 — Unmapped labels are discarded, so a site redesign is invisible
**Done 2026-09-08.** `unmapped_labels` was computed on every lookup and
dropped. It is the only signal a site gives when it renames a field: nothing
errors, the lookup succeeds, resolves less precisely and returns fewer claims
— so a broken adapter reads as a thin pack.

Now a table in `app.sqlite`, one row per (adapter, label) with a `seen` count,
newest first. Accumulate rather than append: a row per sighting would grow
with reading volume while answering a question about *distinct* labels.
Dismissal is a `DELETE`, not a flag, so a label that recurs comes back — the
honest answer to "I dismissed this and it is still happening". The Overview
table strikes a dismissed row through instead of removing it, and puts it back
if the request failed.

It lives in `app.sqlite`, not the store: a pack's adapter is content, what a
reader's browsing revealed about a site is not — it must never move a
`content_digest`, and clearing history must not erase it. The record call is
guarded, because losing the signal is cheaper than losing the reader's answer.

The gate that was missing came with it: `src/app/tests/conftest.py` fails any
test that opens the reader's own `~/.kriko/app.sqlite`. `test_web.py`'s
fixture had been doing exactly that for 54 tests, which is how a new test
first read `seen: 11`.

### B71 — There is no first run
**Already done, closed 2026-09-08 without a change.** The audit row was written
from a screenshot and duplicated work that was already on `main`:
`ui/src/routes/Welcome.svelte` and `ui/src/lib/NextStep.svelte` landed in
`cb27d13` and `d362769` (2026-09-05). `firstRun` fires when `status.packs === 0`
and Welcome offers install-from-index (as a job), install-from-file, and skip.
Recorded rather than deleted, because "the audit found a gap that was not there"
is the useful fact — a screenshot is evidence of what a screen looks like, not
of what the code does.

### B72 — Error copy names exceptions, not next steps
**Done 2026-09-08.** Every error surface in the app named an exception.
"Could not load this view: ConnectionError" and "500: Internal Server Error"
are both accurate and both useless: the reader of a local app has no terminal,
no log viewer and nobody to page, so whatever the screen says is the entire
remedy available to them.

The remedy is derived from the **HTTP status**, in one module
(`ui/src/lib/failure.ts`), never from the view. A per-view table of error copy
would be twenty places to keep in step and the twenty-first view would ship
with none — the same failure mode as any hand-enumerated list in this repo.
Statuses are a closed vocabulary that does not grow with the product, which is
exactly the exception the scalability rule carves out.

Four things every failure now carries: what happened in the reader's terms, the
next action, whether trying again could plausibly work (a retry offered on a
404 is a button with no path to working), and the exception itself — folded
away underneath rather than dropped, because the remedy is what the reader
needs and the exception is what we need when the remedy did not work. A
rejection with no status at all is read as "the engine stopped answering",
which is what it is nine times in ten: the engine is a separate process and can
die while its window stays open.

`Async.svelte` renders `Failure`, so a new view gets this by using `Async` at
all. `Health.svelte` and `Packs.svelte` had to stop storing `(e as Error)
.message` and keep the exception instead — a string has already thrown away the
status the remedy is derived from.

**The gate that was missing.** This was not one bad sentence, it was seven
views each inventing its own, which is what per-view error copy always becomes.
`ui/src/lib/failure.test.ts` scans every `.svelte` source through
`import.meta.glob(..., { query: "?raw" })` and fails on `{error.message}` in
markup or on the old sentence — with a count assertion first, because a glob
that matches nothing passes every check under it.

### B73 — Extension and app versions never handshake
**Done 2026-09-08.** Two headers, both riding on requests that were already
happening: `X-Kriko-Extension` out, `X-Kriko-Minimum-Extension` back. No
poll, no endpoint, no third clock to keep wound — the same reasoning as the
extension *sighting*, which is a side effect of the extension doing its actual
work and therefore cannot be true while the install is broken.

The rule is one number in one place, `extension.MINIMUM_VERSION`, bumped only
when a wire change genuinely breaks an older client. Not a compatibility
matrix: three separate clocks (knowledge weekly, the binary rarely, the
extension again) would make a matrix wrong within a release. The extension
holds the *comparison* and no floor of its own; the dashboard holds neither
and renders the sentence the app wrote. Tests assert all three, because any
one of the files can be edited alone.

Three states, not two: `unknown` (nothing has called) is separate from
`too_old`, because telling a reader who never installed the extension that
theirs is out of date is worse than saying nothing.

**The missing gate came out of it.** Adding `extension_seen.version` revealed
that `CREATE TABLE IF NOT EXISTS` does nothing for a new *column*: the stamp
moves, the script runs, `PRAGMA user_version` is rewritten, and the column is
silently absent on every existing reader's file until the first query names
it. Every prior change to this schema had been a new table, which is exactly
why it survived. `state.add_missing_columns` now reconciles what SCHEMA
declares against `PRAGMA table_info` — parsed off the declaration, never a
migration list to remember — adding only, raising on anything SQLite refuses,
and `test_app_state_migration.py` ratchets the set of columns that could
never be back-added.

### B74 — No route is reachable by keyboard alone end to end
**Done 2026-09-08.** The claim in the audit row was too strong — the rail is
real anchors, the skip control was already first in the tab order, focus
already moves into the view on navigation, and nothing in the app uses a
positive `tabindex`. What was true is that *nothing verified the walk*. Every
keyboard test in the suite covered one route with its own hand-written hash, so
three failures were invisible:

1. A rail entry whose name `App.svelte`'s if-chain does not handle renders
   "No such view" — the link is there, focusable, announced, and there is no
   path to that screen at all, by keyboard or mouse.
2. A screen that renders but has no `NAV` entry is reachable only by typing a
   URL, which in a desktop app with no address bar means not reachable.
3. Focus escaping a modal into the document behind its scrim.

**(3) was a live defect and is fixed.** The palette declared
`aria-modal="true"` and did not keep it: Tab off the last option walked into
the rail behind the scrim — focus on a link the reader cannot see, no visible
ring anywhere on screen, and no reason left to think Escape was listening. It
now wraps at the two ends only, reading its stops off the dialog at the moment
of the press because the list is filtered as the reader types.

**The gates.** `ui/src/App.keyboard.test.ts` walks every destination in `NAV`
— one case per screen rather than a loop, because "which screens are missing"
is the useful answer — and asserts the skip control is first, no positive
tabindex exists, and every destination has a focusable rail link. Driven off
`NAV`, so a screen added tomorrow is covered the day it appears. A source gate
beside it fails any component that claims `aria-modal` without handling Tab,
because the palette is the app's first modal and the second will be written by
someone reading the first.

**One thing this cost, worth writing down:** the first version of the
traversal test was green with a route deleted from the if-chain. `waitFor`
retries until an assertion *passes*, so a negative assertion inside it passes
on the empty first frame and never sees the screen it is judging. Wait for a
positive signal, then assert negatives synchronously.

### B75 — `hover_lite.js` pulls a font from Google Fonts
**Done 2026-09-08** — `bc7ae01`. A content script fetching a webfont from a
third party, on every listing the reader opened: it told Google which cars
they were looking at, from the one component running where that is observable,
and it failed offline — the state the product is designed for. Fonts are
system-first now. The missing gate ships with it, derived from
`app.extension.SHIPPED`: no remote host in anything shipped, by any of the
three spellings of the mistake.

### B76 — Seven other `overflow` sites, unaudited `[G6]`
**Done 2026-09-08** — `1f3978e`. Audited: 346 and 1046 are correct
`overflow-x` on table containers, 524 correct for the job log, and
513/729/968/1130 are clips. Only the rail was wrong. `chrome.test.ts` holds
the rail's shape against the stylesheet, because layout is exactly what jsdom
does not do and a browser harness for one CSS property is not the trade.

### B77–B80 — Onboarding, docs, state management, performance
The long tail from the audit's independent findings. Rows kept together
because none of them blocks 1.0.0 and each is small.

#### B77 — Nothing checked that an onboarding link goes anywhere
**Done 2026-09-08.** The onboarding path itself was already real — `Welcome`
on an empty store, `NextStep` after it, and an `EmptyState` on most screens
whose entire job is to hand the reader somewhere to go. What none of it had was
a check that the somewhere *exists*. The audit's F10 names the symptom rather
than the cause: the Packs empty state pointed at a route that had to be
corrected by hand, once, after a person clicked it.

A dead link in onboarding is the worst dead link in the product. It is the
reader's first minute, they have no model of the app yet to tell them the app
is wrong rather than they are, and what they get is "No such view" — which from
where they sit is indistinguishable from a broken install.

`ui/src/lib/links.test.ts` walks the source for every destination anyone writes
down and asks whether `App.svelte` would render it. Three spellings, because
there are three: a literal `#/name` in markup, a `toHash`/`hashWith` call, and
a route name handed to `NextStep`. The renderable set is read off `nav.ts` and
off `App.svelte`'s own if-chain — including the parametric views that have no
rail entry, which would otherwise have needed the exemption list this file
exists to avoid. Verified red by misspelling one `actionHref`.

**And the one real defect on that screen:** `Welcome` was still printing
`e.message` at the reader, so the first sentence Kriko ever says to someone
could be a `TypeError`. It holds the exception and renders `Failure` now, like
everywhere else.

#### B79 — Eleven views flattened the exception before anything could read it
**Done 2026-09-08.** B72 shipped the mechanism and converted five views; this
is the other eleven, and the gate that stops the twelfth. Every one of them
did the same thing one line earlier than the bug B72's gate was looking for:
`error = String(cause)` in a catch block, into a `$state("")`. By the time the
markup runs there is no status left, so no remedy can be derived however good
the component downstream is — and a gate that reads only markup cannot see it.

Twenty-two sites across eleven files, in nine spellings of the same variable
(`error`, `loadError`, `rowError`, `actionError`, `markError`, `installMessage`,
`detail{}`, `verdict.detail`, a synthesised job `message`). All of them now
hold the exception. Three shapes came out of it, and they are the pattern for
anything new:

* **A view** renders `Failure` — the headline, the next step, a route when the
  remedy is on another screen, the exception folded away underneath.
* **A row** is too small for that block, so it renders `remedyFor(x).headline`
  and nothing else. The sentence is still derived; only the frame is smaller.
* **The Console** renders `remedyFor(x).technical`, because it is the one
  surface whose reader *asked for* the exception. A console answering "that is
  a bug in Kriko" would be hiding the thing they opened it to see.

**Two findings that fell out of the pass.** `Check` was keeping a validation
sentence this app wrote ("paste a link first") and an exception from the engine
in the same string, which meant the reader's own typo and a dead engine
rendered identically — two variables now. And `remedyFor(x).technical` turned
out to be exactly the `(cause as Error).message ?? String(cause)` that four
files had each written by hand, so "the exception as text" has one definition
and the new gate needs no exemptions at all.

#### B80 — 197 KB in one chunk, which nobody had decided
**Done 2026-09-08.** The audit's F16 flagged the bundle "so it is a decision
rather than an oversight", and `src/app/tests/test_bundle_budget.py` is what
makes it the former. The decision recorded there is that there is *no* code
splitting and that this is right: splitting trades one download for several,
which pays on a website, where the second chunk crosses a network and most
visitors never reach the screen it holds. This bundle is read off local disk by
a window the shell only shows after `/api/health` answers, and every reader has
every route — the rail offers all of them and the Console reaches any of them
by name. A lazy route would buy nothing and add a loading state to a screen
that has none.

So size is not something to optimise here, it is something to watch, and the
failure guarded against is not a slow app: it is a dependency arriving that
nobody weighed — a date library, an icon set, a charting package, each
reasonable alone and none visible in a diff. Budgets are per kind and for the
whole payload, generous by about a third, and deliberately **not** a ratchet: a
ratchet that tightens every build turns unrelated commits red and teaches
people to raise the number without reading it. Raising it is fine. Raising it
knowingly is the point. Two more checks ride along — no source maps (a `.map`
ships the source and no per-kind budget names it), and `index.html` asking for
exactly the files present, which catches a stale bundle from the other end.

#### B78 — Docs do not match the code
**Done 2026-09-08.** Ten of the twelve tables in `app.sqlite` were named in no
document at all, and six API surfaces — history, marks, subjects, pipeline,
submissions, extension — had no endpoint written down anywhere. Both fixed in
`docs/INTERNALS.md`: an *Interface State* section with a row per table and why
it is not in the engine's schema, an *other API surfaces* section for the six,
and `routers/focus.py` — the fix for "Open in App opens a browser tab" —
introduced in the Desktop Shell plane, where it had been missing entirely.

**The mechanism, because a docs audit performed by a person is the manual step
G5 forbids** (and backlog B43 already says the prose gate is a worklist, not a
proof). `src/app/tests/test_docs_match_the_code.py` asks questions *of the
code* and looks for the answers in the documents: every table in
`state.declared_columns()`, every API surface walked off the live route table,
the two-database split, the handshake header names, and every path CLAUDE.md's
documentation map cites. Nothing is listed in the test — a thirteenth table or
a new router goes red the day it lands. What it deliberately cannot check is
whether the prose is *right*; it checks that the thing exists in the
sentence-writing surface at all, which is the failure that actually happened.

**Two things this cost, both worth keeping.** The first version asked whether
the string `"focus"` appeared in the docs, and it did — in every sentence about
where focus lands after navigation — so the gate passed while the surface named
`focus` was undocumented. A router whose name is also an English word is
exactly the one a name check misses; the check is by *endpoint path* now, which
is both stronger and the idiom the docs already use. The second: FastAPI keeps
one `_IncludedRouter` per `include_router` call rather than flattening
endpoints into `app.routes`, so the obvious one-level loop found nothing at all
— caught only because the test asserts it found more than ten surfaces before
judging them.

---

## Human decisions — status under G5

| # | Topic | Status |
|---|-------|--------|
| 5 | Source ToS (B18) | **Open** — one-time policy, the only allowed kind under G5 |
| 6 | TR SGM recall feed | **Resolved 2026-08-03** — dropped with all official recall sources (B17) |
| 7 | B11 emissions sign-off | **Resolved 2026-08-03** — cancelled; derive or fail open (G5) |
| 8 | Split point for `knowledge/`'s deletion (B33 Phase 6b) | **Resolved 2026-08-29** — generic ledger/extract to `kriko/`, cars-specific pipeline to `packs/cars/pipeline/` |
| 9 | Does a bare mileage figure earn the specificity escape for routine-wear claims? (B36) | **Open** — product-principle taste call, not a mechanism gap |
| 10 | No LICENSE file, despite README calling Kriko "open" (B44) | **Open** — which licence (if any) to publish under |
