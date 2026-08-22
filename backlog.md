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

### B26 — Settle the 696 `status: review` claims deterministically `[G1][G5]` *(new 2026-08-19)*
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

### B28 — Split `ops/hub/web.py` into routers `[G5]` *(new 2026-08-22)*
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

---

## Human decisions — status under G5

| # | Topic | Status |
|---|-------|--------|
| 5 | Source ToS (B18) | **Open** — one-time policy, the only allowed kind under G5 |
| 6 | TR SGM recall feed | **Resolved 2026-08-03** — dropped with all official recall sources (B17) |
| 7 | B11 emissions sign-off | **Resolved 2026-08-03** — cancelled; derive or fail open (G5) |
