# Kriko — Done

Completed work, newest first. Entries move here from `backlog.md` with date + commit.
Seeded 2026-07-16 from git history; older history lives in `git log` and
`docs/pipeline_postmortem.md`.

---

## 2026-08-27 — Phase 6a of the pivot: backend/ deleted, catalog into the pack

Commits `e5d7951` (code) and this one (docs + one engine bug). Suite 534 -> 536,
and 3 minutes -> 16 seconds now that nothing starts Postgres.

- **`backend/` and `deploy/` deleted** — sync ETL, SQLAlchemy models, the
  650-line resolver, matcher, normalize, recover, equipment, the FastAPI api,
  the Dockerfile and compose stack. Every one has a successor from Phases 1-5.
  `ops/{hub,mcp,reports,swap.py}` went with them.
- **The car catalog moved** to `packs/cars/data/`, and every reader was
  repointed rather than left to guess.
- **`ops/reports/coverage.py` -> `packs/cars/coverage.py`.** Its one engine
  dependency went away with it: it imported `SERVABLE_STATUSES` from the deleted
  resolver, and now derives servability from the pack manifest's
  `[status_confidence]` table — the same authority `build.py` uses, so the
  report and the builder can no longer disagree about what "servable" means.
- **Layering re-derived**, not renamed: the column (`ops -> backend ->
  knowledge`) became a fan (`apps -> kriko <- packs -> knowledge`, with `ops`
  driving). Four invariants enforced in `test_repo_invariants.py`, plus a
  ratchet asserting `backend/` stays deleted — a package deletion is easy to
  undo by accident.
- **`README.md` and `CLAUDE.md` rewritten** for the pack architecture. Every
  command in the README was executed before being documented, which is how the
  next two items were found.

Two bugs the smoke test found, neither of which any unit test could have:

- **`python -m apps.web` did not exist.** `app.py`'s own docstring and the
  README both document the package form; only `python -m apps.web.app` worked.
  Added `apps/web/__main__.py`.
- **A contradicting identity attribute was silently dropped once the candidate
  set was down to one** (`kriko/lookup/match.py`). Narrowing was skipped at
  `len(candidates) <= 1` as an optimisation — but narrowing is also how a
  contradiction is *detected*, so the skip made the most confident-looking case
  the only silent one. Live effect: a Sahibinden ad for a 1.6 TDI Golf 7 saying
  "Otomatik" resolved `exact` onto the sole manual variant, returned **zero**
  gearbox claims, and raised no flag — the quiet zero G3 exists to prevent. Now
  flagged `soft_narrow_fallback:transmission`. The fix can only add flags, never
  change which subjects match, which the 98-row parity golden confirms.

  The missing 1.6 TDI DSG catalog row is deliberately **not** patched: per the
  generalization principle a per-model fix does not exist, and the gap is now
  visible to B19's loop instead.


## 2026-08-26 — Phase 0 of the knowledge-engine pivot: demolition

First commit of goal **G6** (see `backlog.md`). Baseline established at 768 passing,
then 12 files and ~1,500 LOC removed; suite 768 -> 741 (27 tests deleted with their
modules) and 52s faster.

- **`ops/auto.py` (635) deleted.** The legacy curated-YAML pipeline. The ledger flow
  (`acquire -> ingest -> extract -> resolve -> cluster -> verdict -> export`) is the
  one pipeline now. Its only importer was `ops/tests/test_auto_cap.py`.
- **`knowledge/discover.py` (532) deleted.** A Textual TUI for approving YouTube
  sources by hand — a human in the data path, which G5 forbids. Its only importer was
  `ops/auto.py:272`; the two went together.
- **`knowledge/ledger/feeds/` deleted** (nhtsa, safety_gate, recalls_tr, `__init__`)
  plus three tests, plus the `feeds` stage unwired from `ops/ledger_run.py` — its
  argparse flags (`--feed`, `--make`, `--model`, used by nothing else), the
  `_cmd_feeds` body, the dispatch entry, and its slot in the `all` sequence.
  B17 had already dropped the whole recall-feed effort.
- **`add_car.sh` and `scripts/run_local.sh` deleted** — superseded onboarding and
  serving wrappers.
- **`knowledge/gold/gold.yaml` restored.** It was deleted in the working tree but
  still live-referenced by `langextract_client.py:36` and `eval_verdict.py:16`; three
  tests were failing on it. It is car-specific few-shot data and moves to
  `packs/cars/research/few_shot.yaml` in Phase 4.

Checked rather than assumed: deleting `auto.py` does **not** lose part-stub creation.
`_ensure_part_stub` was only its caller — `generate_part_scaffold` stays in
`knowledge/parts/search_templates.py`, `export.py:409` fails open and holds claims
back when a stub is missing, and `ops/remediate.py`'s `missing_part` finding acts on
it. That is B19's loop, which was supposed to own this anyway.

Deferred out of Phase 0, with reasons: **`deploy/` stays** until
`test_repo_invariants.py:124` is retargeted — it reads `deploy/Dockerfile` to enforce
that the serving image never pulls in `mistralai`/`langextract`/`exa-py`, an invariant
that matters *more* once `kriko/pipeline/` and `kriko/lookup/` are siblings.
**Postgres stripping stays** because `backend/` is the parity reference until the old
path is deleted. **`logs/` stays** — `analyses.jsonl` is the source of the parity
corpus Phase 4 depends on.

Docs updated rather than left dangling: `README.md` and `docs/USAGE.md` now show
`ops.ledger_run acquire` + `ops.ledger_run all`; the 23-line YouTube-TUI section is
gone from `USAGE.md` with headings renumbered; `docs/INTERNALS.md` marks the
curated-YAML path legacy and names the live flow.

---

## 2026-08-22 — Refactor pass: delete the archaeology, derive the hand-lists

Seven commits (`dfe2469`..`0caaa64`). ~1,100 lines removed, suite 765 -> 768
(14 obsolete tests deleted, 17 added). Every phase verified with the full suite
before the next started.

- **854 LOC of spent code deleted** (`dfe2469`). Six one-shot migrations whose
  transform already ran on the checked-in YAML (`migrate_v3`, three `backfill_*`,
  `add_part_code`, `strip_fitment_field`) and three zero-reference source modules
  (`sources/forums.py`, `recalls.py`, `specialists.py`). Kept deliberately:
  `doctor.py`, `repair_missing_stub_scaffold.py`, `ops/swap.py`,
  `ledger/parity.py` — standing tools, not spent migrations. `swap check` is a
  documented acceptance gate.
- **`reclassify_maintenance.py` -> `knowledge/maintenance.py`** (`c2b4695`),
  341 -> 259 LOC. Its name and location both misdescribed it: a domain rule, not
  a catalog migration. Stripping the human-sign-off CLI (a path G5 forbids) also
  orphaned `argparse`, `pathlib`, `yaml`, `REPO_ROOT`, `PARTS_DIR` and
  `SERVABLE` — the module now takes a dict and returns a dict.
- **Duplication consolidated where it was real** (`bc4aa6a`). `catalog_models()`
  and `VARIANTS_DIR` (byte-identical across three feeds), `_model_part_hint`
  (identical in two of three), and `PSEUDO_PART_CODES` (four definitions -> one
  in `catalog/registry.py`). **Five other "duplicates" were left alone** and the
  reason recorded at the shared definition: `_now_iso` emits different formats,
  `_http_get` differs by `follow_redirects`, `_doc_text` is three different feed
  schemas, and nhtsa's `_model_part_hint` uses a different algorithm. The grep
  found name collisions, not copies.
- **Onboarding data left Python** (`c647b8e`). `_WIKIPEDIA_ARTICLE_TITLES` (15
  models) and `_ENGINE_ALIASES` moved to
  `knowledge/catalog/wikipedia_articles.yaml`. These genuinely cannot be
  catalog-derived — `discover.py` runs *before* a model has a catalog row and
  exists to create one — so the fix is data, not derivation. The YAML header
  says so, to stop the next reader "fixing" it.
- **`ops/hub/web.py` 1151 -> 831** (`de6202a`), into `textfmt.py`, `agents.py`,
  `claimview.py`. **The planned six-router split is not possible**: endpoints
  read `DATA_DIR`/`RUNS_LOG`/`CLAIM_SIGNAL_LOG`/`AGENT_RUN_LOG` from module
  scope and `test_hub_web.py` patches them via `monkeypatch.setattr(web, ...)`.
  A function resolves globals from the module it was *defined* in, so moving an
  endpoint detaches it from the patch — `/api/models` would read the real
  catalog instead of `tmp_path` and still return 200. Only helpers reading no
  patched global moved; `web.py` re-imports them so every call site and patch
  still resolves. Verified by diffing the 28-route table before and after.

**Two latent bugs surfaced by the dedup pass and fixed separately:**

- **`_default_aftertreatment` drift** (`bf8590c`). Two copies: `backend/sync.py`
  returned `"none"` for a euro4/euro5 diesel, `write_variants.py` returned
  `None`. The dangerous part was *which* was tested — `test_scr_gate.py` covers
  sync's version, but grep shows sync **never calls it**; `write_variants.py:477`
  was the sole production caller, running the untested, divergent copy. A euro5
  diesel was written with no aftertreatment, `_scr_compatible` fails open on
  falsy, and an AdBlue/SCR claim could surface on a car with no SCR hardware.
  Now one implementation in `knowledge/catalog/emissions.py` (knowledge layer,
  because `backend/` may import it but not the reverse), plus a Dockerfile COPY
  line the invariant test demanded.
- **`_SHARED_CODES` stale** (`0caaa64`). Listed clio_5 and golf_7; megane_4 had
  its part files and variant codes but no entry, so regenerating it would have
  dropped `electrical_code`/`body_code` from every row. Now derived from
  `backend/data/parts/{electrical,body}/`, the same pattern
  `catalog_code_manufacturers()` uses.

Both bugs are the failure mode `docs/design_flaws.md` Flaw 1 records for
`SIBLING_CODE_FAMILIES`: a hand-maintained list that drifted. Both fixes make
the *class* impossible — one asserts function identity, the other asserts
`_SHARED_CODES` never returns.

---

## 2026-08-21 — CI, contributor protocol, structural invariants

No `.github/` existed: nothing verified a branch before merge.

- **The documented test command was wrong.** `python -m pytest backend knowledge`
  in the README collected **576 of 761** tests once `ops/` existed — every
  `ops/tests` file skipped, silently, without failing. Root cause: no pytest
  config at all, so collection depended on which directories you named.
  `pytest.ini` now pins `testpaths`; the README says to run `pytest` bare.
- **The layering rule became a test, not a CI script.** Duplicating the greps
  into CI would let them drift from `CLAUDE.md`.
  `ops/tests/test_repo_invariants.py` fails if `knowledge/` imports from
  `backend/` or `ops/`, if `backend/` imports from `ops/`, or if a package with
  tests is missing from `testpaths`. Each was verified to **fail on an injected
  violation** — a guard that cannot fail is not a guard.
- **CI** (`.github/workflows/ci.yml`): the suite with no secrets (verified: all
  761 pass in a stripped environment), the node tests, and a `docker build` that
  imports the serving app inside the image — covering the breakage class the
  suite structurally cannot see.
- **Templates**: PR template checks the CLAUDE.md principles; the claim-quality
  issue template asks which value bar the claim failed.
- **`CONTRIBUTING.md`**: branches, the commit convention already in the history,
  the test gates, the layering rule.
- Stale references refreshed: README architecture + file layout predated `ops/`;
  `knowledge/requirements.txt` still cited `judge.py` (deleted) and the old
  `knowledge/hub`, `knowledge/mcp` paths.

765 pytest (761 + 4 invariants), 23 node.

**CI is two jobs, ~3 min/push.** The docker-build job was dropped after the fact:
the repo is private so Actions minutes are billed, and the build was 3-5 of ~10
minutes per push. Its value is preserved statically —
`test_dockerfile_copies_every_knowledge_module_the_serving_path_imports` computes
the transitive closure of `knowledge/` imports reachable from `backend/` (12 files
today) and asserts `deploy/Dockerfile` copies each. Verified by deleting the
`title_sim.py` COPY, which is the near-miss that happened for real during the
refactor. It does not replace a build — a broken `pip install` or bad base image
still needs one.

**Open, not fixed here:** `package-lock.json` is gitignored, so CI uses
`npm install` rather than `npm ci` — no reproducible install. And `README.md`'s
onboarding step still says "human fills in per-market hp/years", which contradicts
the automation principle in `CLAUDE.md`.

---

## 2026-08-21 — Codebase organisation: five phases, backend/knowledge cycle broken

Spec: `docs/superpowers/specs/2026-08-21-codebase-organisation-design.md`.
Baseline before: 760 passed / 1 failed, 52 dirty files, 463 tracked files.
After: 761 passed / 0 failed, clean tree, 310 tracked files.

- **Phase 1 — dirty tree committed** in six coherent commits: source tiers,
  component registry, part YAML v3, serving payload v2, hover_lite v2 rendering,
  hub picker. The pre-existing test failure was a harness bug, not a product
  bug: `test_hub_web.py` regex-scans `hub.js` for `$('#id')` selectors without
  stripping comments, so a comment *documenting* a past selector bug read as a
  live lookup. Now strips `//` and `/* */` first.
- **Phase 2 — git hygiene.** `knowledge/ledger.db` was gitignored *and* tracked;
  gitignore never untracks, so the 6.9 MB binary re-diffed on every commit and
  rode along in three. Untracked with the hub run log and `sahibinden_example/`
  (152 files, 7.8 MB, referenced by nothing). Tracked files 463 → 309.
- **Phase 3 — seven dead modules deleted** (`knowledge/` 21 → 13). All leaves:
  zero importers, every apparent reference a self-reference in its own docstring.
  Five were already on the 2026-07-07 ledger plan's delete list, which was only
  half executed. Two were per-model patches the generalization principle
  forbids — `fix_sibling_contamination.py` imports the very
  `stoplists.mentions_sibling_code` that now prevents what it was written to mop.
- **Phase 4 — `docs/historical/`** for the two "do not follow" docs plus
  `thoughts/`. `pipeline_postmortem.md` deliberately stayed: three live files
  cite it as a standing convention. `CLAUDE.md` and `README.md` both listed
  `kriko_build_plan.md`, which exists nowhere — dangling reference dropped.
- **Phase 5 — the dependency cycle.** `backend/` and `knowledge/` imported each
  other; 12 of 18 cross-boundary imports sat inside function bodies as
  `ImportError` workarounds. Root cause: `backend/tools/` held operator analysis
  tooling — nothing in `backend/api`, `core`, `db` or `sync.py` imports it, while
  the hub, ledger, MCP server and pipeline imported `backend.tools.coverage` from
  six places. New `ops/` layer (layer 3) now holds `reports/`, `hub/`, `mcp/`,
  `auto`, `process`, `ledger_run`, `swap`, `remediate`, `panel`; `title_sim`
  moved down into `knowledge/`. **`knowledge/` now imports nothing above it and
  `backend/` nothing from `ops/`** — enforced by two greps in `CLAUDE.md`'s new
  layering principle and documented in `INTERNALS.md` ("Two Planes" → "Three
  Layers"; it also still named `judge.py`/`promote.py`, long gone).

CLI paths changed with the module moves — `python -m backend.tools.coverage` →
`ops.reports.coverage`, `knowledge.auto` → `ops.auto`, `knowledge.ledger.run` →
`ops.ledger_run` — along with `.mcp.json`, `opencode.json`, `package.json`'s test
glob, and the command strings `ops/hub/web.py` spawns and validates.

Verified at every step: 761 pytest + 23 node tests, `docker build`, and
`import backend.core.resolver, backend.sync, backend.api.main` inside the built
image — the last catching a `COPY` the test suite structurally cannot see.


## 2026-08-19 — B24: agent methodology overhaul — rules move to the write path

The first live agent onboarding (VW Golf 8) wrote four **marketing trims**
(Impression/Life/Style/R-Line) describing two powertrains, with `7-speed DSG`
as a part code and `generation: null`. `submit_trims` returned success; the
breakage surfaced hours later in `backend/tests/test_catalog.py` — a test the
agent never runs. Root cause, generalized: **every rule that lives only in a
test or a prompt is a rule the agent can break and be told "OK".**

- **`knowledge/catalog/identity.py`** — one definition of what makes two cars
  different: `find_overlaps` (imported by `backend/tests/test_catalog.py`, so
  CI and the write gate cannot disagree), `collapse_duplicates`, the code
  vocabulary (`code_errors` refuses descriptions like `7_speed_dsg` and
  sibling-shared families like `dsg`), and `canonical_variant_id`.
- **`knowledge/catalog/doctor.py`** — the same rules applied to the catalog
  already on disk, for every car, unattended: normalize codes, rename
  trim-shaped ids, merge duplicate powertrains, prune orphan fitment rows, fail
  open (`draft: true`) on an unresolvable code. **Preserves the B16 fitment
  remap** rather than re-projecting fitment from variant fields (which would
  have silently pointed `megane4_h5f_100` back at a part file the swap merged
  away — caught by a test). Idempotent; CI gate on the live catalog.
- **`knowledge/agent/gates.py`** — the CLAUDE.md product principle enforced at
  `add_evidence`/`add_document` instead of requested in a prompt: warning-light
  items, ekspertiz-routine items, DTC litanies, filler rationales, blocked
  forum/spec-farm sources, the 5-document per-part budget, and rephrasings of a
  chronic already on file (dq200 carries ~30 rows of the same two failures —
  the B5 volume problem at its source). Reuses `stoplists.py`, with its
  specificity escape valve, so the agent path and the LLM path judge value
  alike. Calibrated against the live catalog: 10 of 699 claims rejected, each
  one a row the product principle says should not exist — pinned as a test.
- **`research_brief(part_id)`** — the agent's plan, derived from
  `components.yaml` + `source_tiers.yaml` + what is already on file + remaining
  budget. "Do web research" was the weakest instruction in the contract.
- **`finish_model(make, model, notes)`** — pipeline pass plus a recorded
  outcome in `logs/agent_runs.jsonl`, so a run's result outlives its session.
- **One contract, generated harness files** — `knowledge/agent/kriko_research.md`
  is the body; `knowledge.agent.render` writes `.claude/` and `.opencode/`
  copies; `test_agent_contract.py` fails on drift and on a granted tool the
  server does not expose.
- **Golf 8 fixed by the mechanism, not by hand**: `doctor --fix` merged it to
  two powertrain rows, renamed the ids, and left one honest finding —
  `7_speed_dsg` needs research.

Commit `e5c00de`. 754 tests (was 698 + 1 failing).

## 2026-08-19 — B25: kriko-hub — claim inspector, catalog doctor, real HTML page

- **The review queue is gone.** Approve rewrote `status: review` →
  `verified` inside a part YAML: a human decision in the data path, which G5
  rules out, and unusable at scale anyway — the live queue holds **696**
  claims, which nobody was ever going to hand-approve. It becomes a **claim
  inspector**: each claim carries the deterministic gate's verdict *with its
  reasons* (the same `knowledge/agent/gates.py` the MCP write path runs), and
  agree/disagree records a labelled example in `claim_signals.jsonl`. A rule
  that collects disagreement is a rule to fix in `gates.py` — where the fix
  applies to every car.
- **Catalog doctor over HTTP** — `/api/doctor` (findings split auto-fixable vs
  needs-research) and `/api/doctor/repair` ($0 deterministic pass), surfaced on
  the Coverage tab. `/api/agent-runs` shows what agent passes achieved.
- **The page is a real `static/index.html`**, not a Python string that once
  took the whole dashboard out via a stray escape (49aa90c). Two consistency
  tests: every element `hub.js` reaches for exists, and every tab it switches
  between has both a nav button and a page div — the second found a live
  drift on the first run.
- **Repo hygiene**: nine `imgui.ini` files committed under garbage names
  (`Constant with a value of 2`, `\240b\235\017`) by the deprecated
  DearPyGui hub, plus `ops/hub/app.py` itself and its `dearpygui`
  requirement, retired. The web hub has been the live one since 2026-08-04.

Commit `89ba247`. 759 tests.

---

## 2026-08-16 — B23: agent-driven model onboarding (closes B21, deprioritizes B22)

Onboarding a car no longer requires a human to hand-type a Python dict. B21's
agent could only start from a coverage finding that already named a `part_id`,
so a car with no scaffold was unreachable — and building that scaffold meant
editing `TR_MARKET_TRIMS` in `knowledge/catalog/write_variants.py`, the exact
hand-enumerated per-model list the scalability rule forbids. The researcher
agent now supplies the trim lineup from the web instead.

- **`write_variants.run(trims=...)`** — injection point; `TR_MARKET_TRIMS`
  demoted to CLI fallback. Row content verified identical for every already
  onboarded car (only pre-existing `notes` drift on `volkswagen_golf_7`).
- **`validate_trims()`** — deterministic structural checks (fuel/transmission/
  emissions vocabularies, year and power ordering, identity keys, duplicate ids).
  An **unsourced figure is not an error**: the row is written `draft: true`,
  `backend/sync.py` skips it, the coverage report raises `draft_variant`. Fail
  open rather than guess — a guessed figure is a silent wrong answer to a buyer.
- **MCP `onboard_model()` + `submit_trims()`** — the model entry point and
  scaffold write (variants + fitment, with the lineup's source pages recorded as
  `spec` documents). 13 → 15 tools.
- **Grounded quotes** — `add_evidence()` rejects any quote not literally present
  in the submitted document (casefold + whitespace-normalized). Previously
  `quote_grounded` was `bool(quote)`, so a fabricated citation was
  indistinguishable from a real one downstream.
- **Harness-agnostic wiring** — `.mcp.json` + `.claude/agents/kriko_research.md`
  (Claude Code) beside the opencode pair; Codex/Cline snippets in USAGE §4e.
  Validation lives in the server, so hosts are interchangeable and none can
  bypass the gates.
- **Agent loop** — one *model* per pass (was one part).
- 580 tests pass; 33 new (`test_write_variants_agent_trims.py`, MCP tool tests).

## 2026-08-04 — B20 + B21: kriko-hub desktop dashboard + MCP control layer

- **B20 — `ops/hub/`** (DearPyGui, deps: `dearpygui`): six clickable
  windows — Overview (spend bar-plot, cost-to-finish, log tails), Model &
  Make (parts → claims/variants/findings), Sources (documents → raw text),
  Extraction (run buttons spawning `ops.ledger_run` with `--max-usd`
  caps, streaming output), Ledger browser (generic read-only SQLite
  explorer), Scaffold (coverage findings). ~1s read-only DB poll; GUI-free
  `metrics.py` pinned by tests; `run.py` gained `verdict --import-only`.
- **B21 — `ops/mcp/server.py`** (stdio MCP, `mcp>=1.0,<2.0` — 2.0
  dropped FastMCP): 13 tools, read + $0 write. `add_document`
  (hash-idempotent) → `add_evidence` (extractor_version=1, (doc_id,title)
  deduped) → `run_pipeline_pass` (resolve/cluster/import-verdicts/export,
  logged `model=agent, usd=0`). Import-verdict predicate generalized
  `{0}` → `⊆ {0,1}` so agent evidence never queues a paid verdict
  (extractor-version-2 evidence still does). Wired in `opencode.json`
  (`mcp.kriko`, type local, `.venv/bin/python`), agent loop in
  `.opencode/agents/kriko_research.md` (coverage → part → research with
  native web tools → write ≤5 docs → pipeline pass → verify).
- **Effect**: new-model onboarding drops from ~$0.17–0.20 to **$0.00** via
  the agent; DeepSeek API demoted to optional accelerator. Suite 536 tests.

---

## 2026-08-03 — B16 catalog swap LANDED ($0 gate policy; no commit yet)

- **Acceptance gate PASSES** under the $0 policy: 0 lost claims (sourceless
  legacy claims = unverifiable provenance; in-ledger/pending = adjudicated;
  YouTube URLs = retry-owned by the remediate loop), 0 match-loss serving
  regressions on the 43-listing replay (current-vs-post-swap), coverage
  findings 18→9.
- **Swap applied in-place**: backend/data/parts/ now serves the ledger export
  (699 claims, 21 parts incl. dw5/dw6 with 17 claims each — the empty-gearbox
  gap closed); 25 legacy files superseded (power-split deleted, non-split
  overwritten), fitment remapped k9k_110→k9k etc. Serving DB re-syncs on
  deploy.
- **Two swap-caught bugs fixed**: (a) `code_family_extra` sibling aliases
  (r9m/M9R) were lost in the power merge — `component_part_meta` copies them
  and `apply` preserves them from superseded legacy files; (b) resolver
  `_best_in_cluster` mutated persisted ORM claims (first analysis rewrote the
  DB row → replay nondeterminism) — merged views now built on transient
  copies.
- **Legacy gate stack retired**: judge.py, promote.py, purge_*.py ×4,
  translate_claims.py, eval_judge.py, review_tool.py + 7 test files (75
  tests) deleted; `ops.process` promote steps raise with a pointer to
  `ledger.run remediate`. The sibling-code guard survives in the sync
  validator + verdict prompt. Suite: 519 passed.
- **Cost accounting (whole wave)**: $0.62 total LLM spend (2.66M tokens) for
  the 3-model catalog; steady-state is $0 (remediate defaults to import-only,
  `--max-usd 0`); new parts cost ~$0.17 one-time when explicitly funded.

## 2026-08-03 — Remediate loop live run + parity-lost self-closing (no commit yet)

- **First live remediate run** (coverage-driven, budget-capped): researched the 9
  zero-claim parts (dw5/dw6 now have 10/16 exported claims), 389 LLM calls for
  $0.17; backfilled the legacy cache (+234 docs, +1138 evidence rows); export
  regenerated (19 parts, dw5/dw6 covered).
- **Parity re-classification**: legacy claims with zero source URLs (~331 —
  mostly body/elec era claims) were counted as "never extracted"; they are
  unverifiable provenance — no URL means no evidence path, and the ledger's
  ≥1-grounded-source bar would never serve them. New category "no source URLs
  in legacy claim (unverifiable provenance)" in `parity.explain_only_old` —
  attributable, not lost. Gate lost count: 124 → 49.
- **Lost-source self-closing loop** (`remediate.lost_source_urls` /
  `ingest_lost_sources`): every parity-lost claim's cited URLs are fetched +
  ingested into the ledger (target_hint = claim's part stem) before the
  extract/cluster/verdict pass — the 49 remaining losses are now ingestible
  pages, not orphans. Tests added; suite 591.
- **Second live run**: ingested the 49 lost pages (+50 docs total), then hit
  **`Insufficient Balance` on the DeepSeek API** — extraction/verdicts pending,
  fully resumable. Once funded: `python -m ops.ledger_run remediate
  --max-usd 2.0` → `python -m ops.swap check`.

## 2026-08-03 — B16 swap mechanism + automated acceptance gate (no commit yet)

- **Export regenerated from the ledger** — the checked-in `ledger_export/` had gone
  stale (15 files, missing dq200/dq250/dq381/ea211/ea888/k9k, one bare-list
  artifact). Fresh run: 19 parts, 536 claims; `golf7_cool_cooling` correctly
  skip-and-reported (no catalog identity). Each part file now carries
  `legacy_part_ids` (which legacy power-split files it supersedes) —
  pipeline-derived via the power-collapse rule, no hand list.
- **`ops/swap.py`** — `plan` derives the legacy→merged fitment remap
  from the export, classifies every legacy file (superseded/retained), counts
  fitment edits; `apply` writes export files into `parts/<type>/`, deletes
  superseded power-split files, overwrites non-split ids in place (fixes a
  delete-pass bug that rglob'd away the fresh export files), rewrites fitment
  axes, defaults to a temp copy unless `--in-place`; `check` = the automated
  acceptance gate: parity loss (every absent legacy claim attributable to a
  named gate), serving monotonicity (baseline replayed against current AND
  post-swap catalogs on fresh DBs — 0 match-loss regressions allowed), coverage
  must not add findings. Tests: `test_ledger_swap.py`; suite 589.
- **Live gate state: FAIL, data-gated** — 119 lost claims (75 never extracted,
  23 never ingested, 21 no matching evidence) → B19 remediate loop targets;
  serving: 21/43 listings differ vs current serving, 0 regressions; coverage
  18→11. Swap lands when parity-lost hits 0.
- USAGE.md §4 Step 6 documents plan/check/apply.

## 2026-08-03 — B11 data safe + B19 auto-remediation loop landed (no commit yet)

- **B11 (data, fail-open)**: hand-typed `emissions`/`aftertreatment` removed from
  all 8 Megane 4 variant rows — the unverified `scr` value on
  `megane4_k9k_110_edc` (wrong for 2016–18) no longer serves. All variants fail
  open (no SCR grounding) until evidence-derived values exist.
- **B11 (mechanism)**: year-split `emissions` segments in `write_variants.py` —
  list of `{year_from, year_to, emissions}` per trim emits one variant row per
  era (`{id}__{emissions}` suffix), per-segment aftertreatment derivation,
  window validation. Tests: `test_write_variants_emissions.py`.
- **B11 (visibility)**: new `variant_no_emissions` coverage finding for diesel
  variants without an emissions value — the gap is reported, never a quiet
  wrong value. Tests added to `test_coverage_tool.py`.
- **B19 (driver)**: `python -m ops.ledger_run remediate`
  (`ops/remediate.py`) — coverage findings (zero_claim_part /
  missing_part / auto_variant_no_tx_part, now carrying `part_id`+`axis`
  metadata) drive an unattended acquire → extract → resolve → cluster → verdict
  → export pass. Budget-capped (`--max-usd`), resumable, `--dry-run` prints the
  plan, empty plan spends nothing. Every pass appends `logs/remediation.jsonl`.
  USAGE.md §4b documents scheduling. Tests: `test_ledger_remediate.py`.
- **G5 cleanup**: the draft-row onboarding step ("a human fills in real
  numbers") is retired — `draft_variant` coverage finding makes scaffolded
  rows fail open visibly; USAGE.md's "Promoting & rejecting claims (human
  step)" section replaced with a retired banner (statuses are verdict-stage
  owned). Docs updated to remove human-step language from onboarding.
- Full suite: 583 passed.

## 2026-08-03 — Priority reorganization: full automation + systemic-only (no commit — doc-only)

Two project rules changed in `CLAUDE.md` and the backlog, per the owner:

- **Automation principle (new)** — nothing in the data path waits for human
  verification, spot-checks, or sign-off; extraction and scraping run unattended.
  Where a value can't be derived automatically, fail open + log the gap. One-time
  policy decisions only (ToS, market coverage, source retirement).
- **Generalization principle (strengthened)** — per-model fixes do not exist:
  no per-model research runs, YAML audits, or spot-checks. Every fix is a mechanism
  that runs for all cars, or the feature is cancelled.
- **B17 dropped** — all official recall feeds retired (TR SGM, EU Safety Gate, NHTSA).
  HUMAN DECISION #6 resolved (drop). Ingested rows stay in `ledger.db` as history;
  feed ingesters + `run.py feeds` wiring to be removed/dormant.
- **B11 sign-off cancelled** — HUMAN DECISION #7 resolved: emissions values derive
  from evidence or fail open (no AdBlue claims when unknown); year-split rows where
  mid-life changes exist; hand-typed Megane 4 values must not serve as-is.
- **B19 created** — auto-remediation loop (coverage-report findings + B6
  contradiction signals auto-enqueue ledger acquire/extract + catalog regen).
  Absorbs former B2 (dw5/dw6) and B3 (EDC-auto gap, "manual only in TR" audits),
  whose manual steps are cancelled.
- **B16** — human spot-review sub-step replaced by an automated acceptance gate
  (parity --explain categories + coverage report + serving-baseline replay).
- **B9** — near-miss policy adopted: out-of-window listing still matches, with a
  "year outside known window" note + demand signal. No further decision.
- Remaining human decision: #5 only (B18 source ToS — one-time legal gate).

## 2026-08-02 — Serving-resolution fix + B15/B16/B17/B8 + B11 mechanism (wave 2)

- **Resolver fixed** — EDC Megane analyses stopped resolving transmission claims:
  `_resolve_part_claims` returned IDs instead of claim objects, and the missing
  `_fuel_compatible` import broke the fuel filter. Introduced `_servable_invariants`
  (source-requirement + high-severity-unreviewed gates) shared by both serving paths.
  Full suite 560 passed.
- **B3 (patch) + B6 (mechanism)**: added `megane4_k9k_110_edc` variant + fitment via the
  catalog pipeline; matcher/transmission-gap tests now pin EDC ads → EDC variant with
  `tx_mismatch false`. B6's coverage-gap test stays green via generic fixture variants.
- **B15 (done)**: deploy-staleness guard — `GIT_COMMIT`/`GIT_BUILD_TIME` stamped at image
  build (Dockerfile ARG/ENV, docker-compose, `scripts/run_local.sh`), surfaced via
  `/health`, `/analyze` (`build` field), and the extension footer. Recurrence guard for
  the B4 stale-image class. Tests: `test_build_stamp.py`, `hover_lite.test.js`.
- **B11 (mechanism landed; data at sign-off checkpoint, HUMAN DECISION #7)**: emissions/
  aftertreatment columns + `_scr_compatible`/`_default_aftertreatment` grounding gate in
  `backend/sync.py`; generator support in `write_variants.py`; `test_scr_gate.py`.
  Megane 4 values hand-typed pending spot-check (EDC row 110 ≠ Blue dCi 115 SCR years).
- **B17 (EU half done; TR blocked, HUMAN DECISION #6)**: Safety Gate feed rewritten to
  the official weekly-report XML after the reverse-engineered JSON API died (404);
  validated live — 50 Renault alerts ingested into `ledger.db`, idempotent.
  TR SGM blocked by an anti-bot JS challenge (TSPD); ingester kept, never fatal.
- **B16 (step 1 done)**: export rewritten to the part-dict schema with serving-gate
  fields grounded at export (year windows, mileage thresholds, maintenance);
  skip-and-report retained. Verified live to `/tmp/opencode/ledger_export` (19 parts).
- **B8 (done)**: `_select_capped` now ranks sources by domain reliability + title
  specificity; DeepSeek `json_object` extraction mode fixed.
- **B15/B17 feed run** left resumable in the background (text-hash dedup).

## 2026-07-22 — DB rebuild + evidence-ledger landing (B1/B12, G2/G4)

- **Serving DB rebuilt from YAML after accidental volume deletion** — no data loss
  by design (YAML is the source of truth; `logs/analyses.jsonl` and
  `knowledge/ledger.db` both survived). Rebuild surfaced a real deploy bug:
- **fix(deploy): add knowledge/consequence_tier.py to the image slice** (`56cb8af`) —
  fresh Docker builds crashed at startup (`sync.py` imports the consequence-tier
  module, but the Dockerfile's knowledge/ slice predated the serving overhaul).
  The recreate-from-scratch path had been silently broken since the overhaul
  landed (B15 class). Serving baseline fixture captured for future serving diffs
  (`backend/tests/fixtures/serving_baseline_2026-07-22.json`, 43 logged listings).
- **B1: evidence-ledger Stage 1 landed to main** (`80edf94`, G4: one trunk). Main
  merged into the branch (`bea0f5a`, one `.gitignore` conflict), then the two
  blockers fixed on-branch:
  - **Export skip-and-report** (`767dc82`) — one invalid cluster (DTC-in-title)
    no longer aborts the whole export; offenders are skipped, reported, retained.
  - **Parity stable identity** (`767dc82`) — match on shared source URLs + domain
    agreement instead of verdict-rewritten titles (`matched: 0` → 327 matched,
    95 sibling-reroute moves); cross-domain false matches from multi-claim pages
    guarded by the domain check.
  - **`parity --explain` acceptance report** (`84c2462`) — categorizes all 474
    only-in-existing claims (126 shipped under rewritten titles, ~230 gate drops
    working as designed, ~120 never ingested/extracted → tracked as B16's
    pre-swap review). Artifact: `docs/historical/thoughts/ledger_acceptance_parity_2026-07-22.txt`.
  - Servable catalog deliberately NOT swapped: legacy part YAMLs still serve until
    the export carries serving-gate fields and fitment is remapped (B16).
- **B12 completed** — `evidence-ledger-stage1` and `model-year-claim-windows`
  merged and deleted; `main` is the only trunk.

## 2026-07 (branch `model-year-claim-windows`, pending merge — backlog B12)

### Backlog wave 1 (2026-07-16/17, subagent-driven — merged into the branch)

- **Ad-vs-catalog transmission contradiction surfaced (B6)** (8990d99) — when the ad's
  gearbox matches no candidate variant's transmission and no same-engine alternative row
  exists, the resolver emits a degraded coverage note and logs a catalog-gap signal
  instead of falling back silently.
- **Coverage report + loud sync guard (B7)** (c8201f4) — `python -m ops.reports.coverage`
  maps variant → fitment parts → per-part claim counts and flags any non-`manual`
  transmission/engine code that resolves to a zero-claim part; `sync.py` prints the same
  warning. The "would it recur?" mechanism for the dw5 hole (B2).
- **Per-listing risk-cap regression net (B4)** (22c9117) — investigation proved the cap
  already binds in code; the 39-risk DSG Golf came from a stale deployed Docker image
  predating the cap commit (3672eaa), not a code bypass. Added unit-boundary + e2e
  `/analyze` regression tests pinning the cap. The remaining real fix (make a stale deploy
  visible) is new backlog **B15**.
- **`no_match` demand miner (B10)** (4a173cc → f2481c8 → 52aafa6, merged 19d62db) —
  `python -m ops.reports.demand` aggregates `no_match` `/analyze` log rows into a
  make/model onboarding-demand table, reason-classified (`not_onboarded` / `catalog_gap` /
  `missing_fields`), catalog-derived via `normalize.py` (no hardcoded car names). Review
  fix rounds: shared `observability.load_records` reader hardened against non-dict lines
  (also hardens `read_recent`/`read_by_id`), `missing_fields` derived from `ad_metadata`
  not matcher prose, fixture-catalog tests, majority-casing group labels, data-derived
  table widths.

- **Golf 7 1.2 TSI onboarded; fitment derived from variants** (a780f82) — no more
  hand-maintained fitment for new rows.
- **Scraper robustness pass** (0ada2d6, d697ee3, 6f64eb8) — fuel/year scraped reliably,
  make/model/fuel/year recovered from URL+title when the DOM fails, English-locale
  Sahibinden handled. Killed most of the `(None, 'Golf', None) → no_match` log rows.
- **Serving overhaul, phases A/B/C/E** (0463869, 3672eaa, b3c769b, c483cb5) —
  consequence-tier ranking signal, per-listing risk cap (MAX_RISKS_PER_LISTING=8;
  see backlog B4 for the exemption loophole), maintenance-kind reclassify script,
  specificity escape valve on the inspection-covered judge gate.
- **Model-year claim windows + mileage gates** (08f00a5, 123b2b7, 2960759) — claims
  carry `applies_year_from/to` and mileage thresholds, grounded deterministically;
  resolver hides out-of-window defects (fail-open on missing data).
- **Failure-onset vs service-interval confusion rejected** (59b22c2); **codes for
  never-onboarded components caught** (980e90f).
- **run_local.sh** (60c307d) — serve the API without Docker/Postgres.

## 2026-07 (branch `evidence-ledger-stage1`, unmerged — backlog B1)

- **Evidence-ledger Stage 1 pipeline** (24 commits, ~50c9ed1..434f9ec) — chunked cached
  extraction with budget enforcement, deterministic per-component evidence clustering,
  single batched verdict per cluster (migrated to DeepSeek, hash-cached, concurrent),
  resumable CLI with dry-run + cost report, validated YAML export, parity diff +
  gold-set verdict eval.
- **Deterministic product-value gate over the verdict model** (b9f0b0d) — eval_verdict
  11/11 gold, resolved the acceptance blocker.
- **Data-quality pass** (16dab04, b131d6d) — unreliable-source-domain blocklist,
  German-language evidence leak flagging.
- **AdBlue/SCR variant-scoping design spec** (434f9ec) — spec only; implementation is
  backlog B11.

## 2026-06 → 2026-07 (on `main`)

- **Part-centric "Lego" pipeline** — parts researched once (`backend/data/parts/**`),
  assembled per variant at sync via fitment YAML; catalog discovery scaffolds variants
  and fitment from Wikipedia.
- **Sync-time grounding guards** — transmission-code registry derived from the part
  catalog (no hardcoded code lists), fuel/drivetrain/powertrain compatibility checks
  stop cross-config contamination broadcasting (`backend/sync.py`).
- **Serve-time gates** — equipment gate, ad-stated-transmission gate (manual ad never
  sees DSG-mechanism claims), high-severity human-review gate, title-similarity dedup
  with strongest-signal merge (`backend/core/resolver.py`).
- **Observability** — `logs/analyses.jsonl` + `ops.reports.analyses` / `replay`
  (branch `observability-analyses-log`, merged content on current branch).
- **Docs** — `docs/INTERNALS.md`, `docs/USAGE.md`, `docs/design_flaws.md` (Flaws 1–4
  addressed; 5–6 tracked as backlog B13), `docs/pipeline_postmortem.md`.
