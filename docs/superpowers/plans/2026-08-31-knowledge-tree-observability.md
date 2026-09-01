# Knowledge-tree Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the shape of the evidence behind every shipped claim readable — worst-first — from the engine, the dashboard and MCP, so an agent or a researcher can see which claims are weakly supported instead of only which subjects are missing.

**Architecture:** One new category-free query module in the engine (`src/kriko/lookup/tree.py`) computes four separate weakness signals at read time by reusing `rank.py`'s tier resolution. Three thin callers expose it: a FastAPI router, a new dashboard tab in the existing JS SPA, and one MCP tool. Read-only — no writes, no change to `relevance()`. One producer-side fix ships alongside, because the staleness signal is currently never written by anybody.

**Tech Stack:** Python 3.14, sqlite3, FastAPI + `TestClient`, FastMCP, vanilla ES-module JS, pytest.

**Spec:** `docs/superpowers/specs/2026-08-31-knowledge-tree-observability-design.md`

## Global Constraints

- Run tests as `.venv/bin/python -m pytest -o addopts="" -q`. `pytest.ini` sets `addopts = -q`; a second `-q` suppresses the count line, and bare `python` does not exist in this environment. Baseline for this plan: **613 tests passing**.
- `src/kriko/` may contain **no** category-shaped identifier, in executable positions or in prose, beyond the waivers already in `src/kriko/tests/test_core_is_domain_free.py::ALLOWED_PROSE`. Do not add a waiver. Do not use the words `engine_code`, `make`, `model`, `fuel`, `mileage`, `variant`, `car`, `cars`, `vehicle`, `odometer`, `transmission` in the new engine module — read `BANNED` in that test file before writing prose. Safe generic words for this domain: *specification*, *usage figure*, *product*, *component*, *subsystem*.
- Layering: `src/kriko/` imports nothing from `app/`, `packs/` or `backend/`. `src/app/` may import `kriko`. Enforced by `src/app/pipeline/tests/test_repo_invariants.py`.
- Do **not** reimplement domain→tier→trust resolution. Import `tier_lookup`, `trust_lookup`, `tier_of` from `kriko.lookup.rank`.
- No weighted scalar score anywhere. The ordering is lexicographic over separately-reported signals, and the sort key is a public field so it is inspectable.
- Read-only over the installed store, except Task 2, which changes what three *producers* write going forward and backfills nothing.
- Commit after every task. Push at the end of the plan. Do not ask for review approval.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/kriko/lookup/tree.py` | **new** — `ClaimHealth`, `EvidenceRow`, `ClaimNode`, `SubjectTree`, `weakest_claims()`, `subject_tree()`. The whole query. Category-free. |
| `src/kriko/tests/test_tree.py` | **new** — ordering, two-pack union, empty store, agreement with `rank.py` on tiers. |
| `packs/cars/pipeline/ledger/export.py:363-374` | **modify** — carry `documents.fetched_at` out as `retrieved_at`. |
| `packs/cars/build.py:608-628` | **modify** — write `source["retrieved_at"]` instead of `""`. |
| `src/app/mcp_server.py:352-366` | **modify** — stamp `retrieved_at` with the current UTC time; an agent submitting now *is* the retrieval. |
| `src/app/web/routers/health.py` | **new** — `GET /api/health/weakest`, `GET /api/health/subject/{subject_id}`. |
| `src/app/web/app.py:22,33-39` | **modify** — import and register the router. |
| `src/app/web/static/index.html:16,88-91` | **modify** — a `Health` tab button and its `<section>`. |
| `src/app/web/static/app.js` | **modify** — `renderHealth()` plus its tab wiring. |
| `src/app/web/static/app.css` | **modify** — `.concern` row emphasis, `.signal` cells. |
| `src/app/tests/test_web.py` | **modify** — router tests against a fixture pack. |
| `src/app/tests/test_mcp_server.py` | **modify** — one test for the new tool. |

---

## Task 1: The engine query — `kriko/lookup/tree.py`

**Files:**
- Create: `src/kriko/lookup/tree.py`
- Test: `src/kriko/tests/test_tree.py`

**Interfaces:**
- Consumes: `kriko.lookup.rank.tier_lookup(conn, pack_ids) -> dict[str,str]`, `rank.trust_lookup(conn, pack_ids) -> dict[str,float]`, `rank.tier_of(domain, tiers) -> str`, `kriko.store.packstore.enabled_pack_ids(conn) -> list[str]`.
- Produces, relied on by Tasks 3 and 5:
  ```python
  weakest_claims(conn, pack_ids=None, limit: int = 20) -> list[ClaimHealth]
  subject_tree(conn, subject_id: str, pack_ids=None) -> SubjectTree
  UNKNOWN_STALENESS: str          # "9999" — sorts last
  ClaimHealth(claim_id, pack_id, subject_id, subject_label, title, kind,
              domain, component, subsystem, severity, refuted_by,
              supporting_sources, independent_sources, best_tier, best_trust,
              oldest_retrieved_at, newest_published_at)  # frozen dataclass
      .concern -> tuple[int, int, float, str]
  EvidenceRow(url, domain, quote, stance, independent, tier, trust,
              retrieved_at, published_at)
  ClaimNode(health: ClaimHealth, evidence: tuple[EvidenceRow, ...])
  SubjectTree(subject_id, label, pack_ids: tuple[str, ...],
              claims: tuple[ClaimNode, ...])
  ```

### Background the implementer needs

Four facts established against the live store, all of which shape the code:

1. `evidence.stance` is one of `supports|refutes|qualifies`; **contradiction is already in the data model**, so no text similarity is needed. In today's cars pack there are 719 evidence rows and *zero* `refutes` — the signal is correct and simply unexercised. Tests must supply their own refuting fixture.
2. `evidence.independent` is `1` on all 719 rows today. Count **distinct `source_id`** among supporting rows, not evidence rows: two quotes from one page are one source.
3. All 193 `sources` rows have `retrieved_at = ''` and `published_at = ''`. Task 2 fixes the producers; this module must therefore treat an empty `retrieved_at` as **unknown, sorting LAST (least concerning)**, not as maximally stale. An absent timestamp is not evidence of staleness, and treating it as such would put all 699 legacy claims at the top of the list on a signal carrying no information.
4. 6 of 699 claims have no evidence at all. `weakest_claims()` **excludes claims with zero sources**: absence of evidence is what `coverage_gaps` reports, and `rank.py` deliberately treats a source-free claim as trust-neutral rather than penalised. They still appear in `subject_tree()` with empty evidence, so nothing is hidden.

The `concern` tuple sorts **ascending on every element**, which is the property that makes it explainable in one sentence:

| element | value | ascending means |
|---|---|---|
| `0 if refuted_by else 1` | 0 or 1 | contradicted first |
| `independent_sources` | int | fewest corroborating sources first |
| `best_trust` | float | weakest best source first |
| `oldest_retrieved_at or UNKNOWN_STALENESS` | ISO string | stalest first, unknown last |

- [ ] **Step 1: Write the failing tests**

Create `src/kriko/tests/test_tree.py`:

```python
"""Reading the evidence back out — is what we ship actually well supported?

The fixtures here are built to exercise the four signals separately, because
the whole point of the ordering is that no signal is hidden inside a weighted
score. Two packs, because a cross-pack contradiction is the G6 case: two packs
may disagree and both must survive, ranked.
"""

import textwrap

import pytest

from kriko.lookup.tree import (UNKNOWN_STALENESS, subject_tree,
                               weakest_claims)
from kriko.lookup.rank import tier_lookup, tier_of, trust_lookup
from kriko.pack import build
from kriko.store import ids, packstore
from kriko.store.db import connect

TERMS = """
- {term_id: product, role: subject_kind}
- {term_id: brand, role: attribute, datatype: text, match: {required: true}}
- {term_id: model_name, role: attribute, datatype: text, match: {required: true}}
- {term_id: mech, role: domain}
"""

TIERS = """
domains:
  maker.example.com: {tier: manufacturer}
  spec.example.net: {tier: specialist}
  forum.example.org: {tier: forum_ugc}
"""

ALPHA_TOML = """
[pack]
id = "alpha"
name = "Alpha"
version = "0.1.0"
[identity]
product = ["brand", "model_name"]
"""

ALPHA_SUBJECTS = """
- kind: product
  label: Widget 100
  identity: {brand: acme, model_name: w100}
"""

# Four claims, each weak in exactly one way, so an ordering bug shows up as a
# specific swap rather than as a vague reshuffle.
ALPHA_CLAIMS = """
- subject: {kind: product, identity: {brand: acme, model_name: w100}}
  kind: known_issue
  domain: mech
  severity: high
  text: {en: {title: Refuted item, body: b, advice: a}}
  evidence:
    - {url: "https://maker.example.com/a", quote: It fails., retrieved_at: "2026-08-01"}
    - {url: "https://spec.example.net/a", quote: It does not fail., stance: refutes, retrieved_at: "2026-08-01"}
    - {url: "https://forum.example.org/a", quote: Mine failed., retrieved_at: "2026-08-01"}
- subject: {kind: product, identity: {brand: acme, model_name: w100}}
  kind: known_issue
  domain: mech
  severity: high
  text: {en: {title: Single forum item, body: b, advice: a}}
  evidence:
    - {url: "https://forum.example.org/b", quote: Happened to me., retrieved_at: "2026-08-01"}
- subject: {kind: product, identity: {brand: acme, model_name: w100}}
  kind: known_issue
  domain: mech
  severity: high
  text: {en: {title: Single maker item, body: b, advice: a}}
  evidence:
    - {url: "https://maker.example.com/c", quote: Service bulletin., retrieved_at: "2026-08-01"}
- subject: {kind: product, identity: {brand: acme, model_name: w100}}
  kind: known_issue
  domain: mech
  severity: high
  text: {en: {title: Well sourced item, body: b, advice: a}}
  evidence:
    - {url: "https://maker.example.com/d", quote: Bulletin., retrieved_at: "2026-08-02"}
    - {url: "https://spec.example.net/d", quote: Teardown., retrieved_at: "2026-08-02"}
    - {url: "https://forum.example.org/d", quote: Confirmed., retrieved_at: "2026-08-02"}
- subject: {kind: product, identity: {brand: acme, model_name: w100}}
  kind: maintenance
  domain: mech
  severity: medium
  text: {en: {title: Unsourced maintenance item, body: b, advice: a}}
"""

BETA_TOML = """
[pack]
id = "beta"
name = "Beta"
version = "0.1.0"
[identity]
product = ["brand", "model_name"]
"""

BETA_CLAIMS = """
- subject: {kind: product, identity: {brand: acme, model_name: w100}}
  kind: known_issue
  domain: mech
  severity: low
  text: {en: {title: Beta item, body: b, advice: a}}
  evidence:
    - {url: "https://forum.example.org/z", quote: Beta saw it too., retrieved_at: "2026-07-01"}
"""


def _pack(tmp_path, name, *, toml, subjects, claims):
    root = tmp_path / name
    (root / "vocabulary").mkdir(parents=True)
    (root / "data").mkdir(parents=True)
    (root / "trust").mkdir(parents=True)
    (root / "pack.toml").write_text(textwrap.dedent(toml), encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(TERMS, encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text(subjects, encoding="utf-8")
    (root / "data" / "claims.yaml").write_text(claims, encoding="utf-8")
    (root / "trust" / "source_tiers.yaml").write_text(TIERS, encoding="utf-8")
    return build.build(root, tmp_path / f"{name}.kpack")


SUBJECT = ids.subject_id("product", {"brand": "acme", "model_name": "w100"})


@pytest.fixture
def store(tmp_path):
    conn = connect(tmp_path / "store.sqlite")
    packstore.install(conn, _pack(tmp_path, "alpha", toml=ALPHA_TOML,
                                  subjects=ALPHA_SUBJECTS, claims=ALPHA_CLAIMS))
    yield conn
    conn.close()


@pytest.fixture
def two_packs(tmp_path):
    conn = connect(tmp_path / "store.sqlite")
    packstore.install(conn, _pack(tmp_path, "alpha", toml=ALPHA_TOML,
                                  subjects=ALPHA_SUBJECTS, claims=ALPHA_CLAIMS))
    packstore.install(conn, _pack(tmp_path, "beta", toml=BETA_TOML,
                                  subjects=ALPHA_SUBJECTS, claims=BETA_CLAIMS))
    yield conn
    conn.close()


def _titles(rows):
    return [row.title for row in rows]


# ── the ordering ─────────────────────────────────────────────────────────

def test_a_refuted_claim_is_the_first_thing_on_the_list(store):
    """Shipping a claim while holding a rebuttal is the sharpest concern."""
    rows = weakest_claims(store)
    assert rows[0].title == "Refuted item"
    assert rows[0].refuted_by == 1


def test_a_refuted_claim_outranks_an_uncorroborated_one(store):
    """Three sources do not save it: contradiction is lexicographically first."""
    rows = weakest_claims(store)
    order = _titles(rows)
    assert order.index("Refuted item") < order.index("Single forum item")


def test_fewer_sources_ranks_above_more_sources(store):
    order = _titles(weakest_claims(store))
    assert order.index("Single maker item") < order.index("Well sourced item")


def test_a_weaker_best_source_ranks_above_a_stronger_one(store):
    """Same source count, so the tie breaks on the best tier's trust."""
    order = _titles(weakest_claims(store))
    assert order.index("Single forum item") < order.index("Single maker item")


def test_the_sort_key_is_inspectable_not_implicit(store):
    """`concern` is asserted directly — the order is a consequence, not the spec."""
    by_title = {row.title: row for row in weakest_claims(store)}
    assert by_title["Refuted item"].concern[0] == 0
    assert by_title["Single forum item"].concern[0] == 1
    assert by_title["Single forum item"].concern[1] == 1
    assert by_title["Well sourced item"].concern[1] == 3
    assert (by_title["Single forum item"].concern[2]
            < by_title["Single maker item"].concern[2])


def test_the_ordering_is_stable_across_calls(store):
    assert _titles(weakest_claims(store)) == _titles(weakest_claims(store))


def test_a_refuting_source_does_not_count_as_corroboration(store):
    """Three evidence rows, one refuting: two supporting sources, not three."""
    row = next(r for r in weakest_claims(store) if r.title == "Refuted item")
    assert row.supporting_sources == 2
    assert row.independent_sources == 2


def test_the_best_tier_ignores_the_refuting_source(store):
    """The rebuttal is specialist; the support is manufacturer and forum."""
    row = next(r for r in weakest_claims(store) if r.title == "Refuted item")
    assert row.best_tier == "manufacturer"


# ── absence is not weakness ──────────────────────────────────────────────

def test_a_claim_with_no_evidence_is_not_ranked_as_weak(store):
    """Absence is what coverage_gaps answers. rank.py treats it trust-neutral."""
    assert "Unsourced maintenance item" not in _titles(weakest_claims(store))


def test_a_claim_with_no_evidence_still_appears_in_its_subject_tree(store):
    tree = subject_tree(store, SUBJECT)
    node = next(n for n in tree.claims
                if n.health.title == "Unsourced maintenance item")
    assert node.evidence == ()


# ── unknown staleness is unknown, not stale ──────────────────────────────

def test_a_missing_retrieval_date_sorts_last_not_first(store, tmp_path):
    """An absent timestamp is not evidence of staleness.

    Today every one of the cars pack's 193 sources has an empty
    `retrieved_at`, so ranking blank as maximally stale would put the entire
    catalog at the top of the list on a signal carrying no information.
    """
    conn = store
    conn.execute("UPDATE sources SET retrieved_at = '' WHERE url LIKE '%/d'")
    conn.commit()
    row = next(r for r in weakest_claims(conn)
               if r.title == "Well sourced item")
    assert row.oldest_retrieved_at == ""
    assert row.concern[3] == UNKNOWN_STALENESS


def test_staleness_breaks_a_tie_when_everything_else_matches(store):
    conn = store
    conn.execute("UPDATE sources SET retrieved_at = '2020-01-01'"
                 " WHERE url LIKE '%/c'")
    conn.commit()
    order = _titles(weakest_claims(conn))
    assert order.index("Single maker item") < order.index("Well sourced item")


# ── two packs ────────────────────────────────────────────────────────────

def test_the_list_unions_across_enabled_packs(two_packs):
    rows = weakest_claims(two_packs)
    assert {"alpha", "beta"} <= {row.pack_id for row in rows}


def test_a_subject_tree_reports_every_pack_that_speaks_to_it(two_packs):
    tree = subject_tree(two_packs, SUBJECT)
    assert set(tree.pack_ids) == {"alpha", "beta"}
    assert "Beta item" in [node.health.title for node in tree.claims]


def test_a_disabled_pack_disappears_from_the_list(two_packs):
    packstore.set_enabled(two_packs, "beta", False)
    rows = weakest_claims(two_packs)
    assert "beta" not in {row.pack_id for row in rows}


def test_an_explicit_pack_id_list_narrows_the_query(two_packs):
    rows = weakest_claims(two_packs, ["alpha"])
    assert {row.pack_id for row in rows} == {"alpha"}


# ── empty and missing ────────────────────────────────────────────────────

def test_an_empty_store_returns_an_empty_list_not_an_error(tmp_path):
    conn = connect(tmp_path / "empty.sqlite")
    assert weakest_claims(conn) == []
    conn.close()


def test_an_unknown_subject_returns_an_empty_tree_not_an_error(store):
    tree = subject_tree(store, "no-such-subject")
    assert tree.claims == ()
    assert tree.label == ""


def test_the_limit_is_honoured(store):
    assert len(weakest_claims(store, limit=2)) == 2


# ── one tier-resolution path, not two ────────────────────────────────────

def test_the_tree_and_rank_agree_on_every_tier(store):
    """A second tier-resolution path is exactly the duplication two earlier
    passes existed to delete. This asserts there is only one."""
    tiers = tier_lookup(store, ["alpha"])
    trusts = trust_lookup(store, ["alpha"])
    tree = subject_tree(store, SUBJECT)
    seen = 0
    for node in tree.claims:
        for row in node.evidence:
            expected = tier_of(row.domain, tiers)
            assert row.tier == expected
            assert row.trust == trusts[expected]
            seen += 1
    assert seen > 0
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest -o addopts="" -q src/kriko/tests/test_tree.py
```

Expected: collection error — `ModuleNotFoundError: No module named 'kriko.lookup.tree'`.

If instead you get an error from `packstore.set_enabled` or `ids.subject_id` not existing, check the real names in `src/kriko/store/packstore.py` and `src/kriko/store/ids.py` and fix the test — do not invent a shim.

- [ ] **Step 3: Write the implementation**

Create `src/kriko/lookup/tree.py`:

```python
"""Reading the shape of the evidence back out.

`lookup` answers "what should this reader be told". This module answers the
other question, the one nothing could ask before: *how well supported is what
we are telling them?*

Four signals, reported separately and never collapsed into a score:
contradiction, corroboration, the best source's trust, and how long ago we
last saw the page. A weighted sum would need weights nobody can justify and
would hide which signal fired, so the ordering is lexicographic instead — and
the sort key is a public field, so a reader can disagree with the order by
looking at it rather than by guessing.

Computed at read time from the same rows `rank` uses, and reusing `rank`'s
tier resolution rather than repeating it. Nothing here is written down: install
a better source-tier table and the answer changes with no rebuild.
"""

from dataclasses import dataclass

from kriko.lookup.rank import DEFAULT_TIER_TRUST, tier_lookup, tier_of, trust_lookup
from kriko.store.packstore import enabled_pack_ids

#: Sort value for a source with no retrieval date. An absent timestamp is not
#: evidence of staleness, so unknown sorts LAST — least concerning — rather
#: than first. Ranking blank as ancient would put every legacy row at the top
#: of the list on a signal that carries no information at all.
UNKNOWN_STALENESS = "9999"


@dataclass(frozen=True)
class EvidenceRow:
    url: str
    domain: str
    quote: str
    stance: str          # supports | refutes | qualifies
    independent: bool
    tier: str
    trust: float
    retrieved_at: str    # when WE last saw the page. '' = unknown.
    published_at: str    # when the WORLD published it. Reported, never ranked.


@dataclass(frozen=True)
class ClaimHealth:
    """One claim's identity plus the four signals, each still separate.

    `independent` and `stance` are flags the *producer* supplied. They are
    claims about the evidence, not verified facts, and any surface showing
    them owes the reader that distinction.
    """

    claim_id: str
    pack_id: str
    subject_id: str
    subject_label: str
    title: str
    kind: str
    domain: str
    component: str
    subsystem: str
    severity: str
    refuted_by: int
    supporting_sources: int
    independent_sources: int
    best_tier: str
    best_trust: float
    oldest_retrieved_at: str
    newest_published_at: str

    @property
    def concern(self) -> tuple[int, int, float, str]:
        """The lexicographic sort key, ascending on every element.

        Contradicted first, then fewest independent sources, then weakest best
        source, then stalest. Ascending throughout is what makes the ordering
        explainable in one sentence, and adding a fifth signal later appends an
        element instead of re-tuning four weights.
        """
        return (
            0 if self.refuted_by else 1,
            self.independent_sources,
            self.best_trust,
            self.oldest_retrieved_at or UNKNOWN_STALENESS,
        )


@dataclass(frozen=True)
class ClaimNode:
    health: ClaimHealth
    evidence: tuple[EvidenceRow, ...]


@dataclass(frozen=True)
class SubjectTree:
    subject_id: str
    label: str
    pack_ids: tuple[str, ...]
    claims: tuple[ClaimNode, ...]


_ROWS = """
SELECT c.claim_id, c.pack_id, c.subject_id, c.kind, c.domain, c.severity,
       c.component, c.subsystem,
       s.label            AS subject_label,
       COALESCE(t.title, '') AS title,
       e.stance, e.independent,
       COALESCE(src.domain, '')       AS source_domain,
       COALESCE(src.url, '')          AS url,
       COALESCE(e.quote, '')          AS quote,
       COALESCE(src.retrieved_at, '') AS retrieved_at,
       COALESCE(src.published_at, '') AS published_at
  FROM claims c
  JOIN packs p USING (pack_id)
  JOIN subjects s ON s.subject_id = c.subject_id AND s.pack_id = c.pack_id
  LEFT JOIN claim_text t ON t.claim_id = c.claim_id AND t.pack_id = c.pack_id
                        AND t.lang = ?
  LEFT JOIN evidence e ON e.claim_id = c.claim_id AND e.pack_id = c.pack_id
  LEFT JOIN sources src ON src.source_id = e.source_id
                       AND src.pack_id = e.pack_id
 WHERE p.enabled = 1 AND c.pack_id IN ({marks}){extra}
"""


def _packs(conn, pack_ids):
    return list(pack_ids) if pack_ids else enabled_pack_ids(conn)


def _nodes(conn, pack_ids, *, subject_id=None, lang="en"):
    """Every claim in scope, folded with its evidence. One query, one pass.

    The fold happens in Python rather than SQL because tier resolution is not
    expressible as a join: `tier_of` applies exact, parent-domain, substring
    and default rules in order. Doing it here is what keeps a single
    tier-resolution path in the codebase.
    """
    packs = _packs(conn, pack_ids)
    if not packs:
        return []

    marks = ",".join("?" * len(packs))
    extra = " AND c.subject_id = ?" if subject_id else ""
    args = [lang, *packs] + ([subject_id] if subject_id else [])

    tiers = tier_lookup(conn, packs)
    trusts = trust_lookup(conn, packs)
    unknown = DEFAULT_TIER_TRUST["unknown"]

    grouped: dict[tuple[str, str], dict] = {}
    for row in conn.execute(_ROWS.format(marks=marks, extra=extra), args):
        key = (row["claim_id"], row["pack_id"])
        bucket = grouped.setdefault(key, {"row": row, "evidence": []})
        if row["url"] or row["quote"]:
            tier = tier_of(row["source_domain"], tiers)
            bucket["evidence"].append(EvidenceRow(
                url=row["url"],
                domain=row["source_domain"],
                quote=row["quote"],
                stance=row["stance"] or "supports",
                independent=bool(row["independent"]),
                tier=tier,
                trust=trusts.get(tier, unknown),
                retrieved_at=row["retrieved_at"],
                published_at=row["published_at"],
            ))

    return [_node(bucket) for bucket in grouped.values()]


def _node(bucket) -> ClaimNode:
    row, evidence = bucket["row"], tuple(bucket["evidence"])

    refuted_by = sum(1 for e in evidence if e.stance == "refutes")
    supporting = [e for e in evidence if e.stance != "refutes"]

    # Distinct URL, not distinct evidence row: two quotes off one page are one
    # source, and counting rows would let a single chatty page look corroborated.
    supporting_sources = len({e.url for e in supporting if e.url})
    independent_sources = len({e.url for e in supporting if e.url and e.independent})

    best = max((e for e in supporting), key=lambda e: e.trust, default=None)
    retrieved = sorted(e.retrieved_at for e in supporting if e.retrieved_at)
    published = sorted(e.published_at for e in supporting if e.published_at)

    return ClaimNode(
        health=ClaimHealth(
            claim_id=row["claim_id"],
            pack_id=row["pack_id"],
            subject_id=row["subject_id"],
            subject_label=row["subject_label"],
            title=row["title"],
            kind=row["kind"],
            domain=row["domain"],
            component=row["component"],
            subsystem=row["subsystem"],
            severity=row["severity"],
            refuted_by=refuted_by,
            supporting_sources=supporting_sources,
            independent_sources=independent_sources,
            best_tier=best.tier if best else "unknown",
            best_trust=best.trust if best else 0.0,
            oldest_retrieved_at=retrieved[0] if retrieved else "",
            newest_published_at=published[-1] if published else "",
        ),
        evidence=evidence,
    )


def weakest_claims(conn, pack_ids=None, limit: int = 20) -> list[ClaimHealth]:
    """The claims we ship that are least well supported, worst first.

    Claims with **no** evidence at all are excluded, not ranked last: absence
    of sources is what the coverage report answers, and `rank` deliberately
    treats a source-free claim as trust-neutral rather than penalised — an
    interval-based item is not less true for lacking a citation. They remain
    visible in `subject_tree`, so nothing is hidden by this.
    """
    ranked = sorted(
        (node.health for node in _nodes(conn, pack_ids) if node.evidence),
        key=lambda health: (health.concern, health.claim_id),
    )
    return ranked[:limit]


def subject_tree(conn, subject_id: str, pack_ids=None) -> SubjectTree:
    """One subject, every claim about it, every piece of evidence under each.

    Unions across packs: a subject with the same identity hashes to the same
    id in every pack, so two packs contradicting each other about one product
    show up here side by side rather than one silently winning.

    An unknown subject is an empty tree, not an error. A fresh install knows
    nothing and that is not a failure.
    """
    nodes = sorted(
        _nodes(conn, pack_ids, subject_id=subject_id),
        key=lambda node: (node.health.concern, node.health.claim_id),
    )
    return SubjectTree(
        subject_id=subject_id,
        label=nodes[0].health.subject_label if nodes else "",
        pack_ids=tuple(sorted({node.health.pack_id for node in nodes})),
        claims=tuple(nodes),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest -o addopts="" -q src/kriko/tests/test_tree.py
```

Expected: all pass. Then the whole suite plus the domain-free gate:

```bash
.venv/bin/python -m pytest -o addopts="" -q
```

Expected: 613 + the new tests, 0 failures. If `test_core_is_domain_free.py` fails, **fix the prose in `tree.py`** — do not add an `ALLOWED_PROSE` waiver.

- [ ] **Step 5: Commit**

```bash
git add src/kriko/lookup/tree.py src/kriko/tests/test_tree.py
git commit -m "feat(engine): read the shape of the evidence back out, worst first"
```

---

## Task 2: Make the staleness signal real — three producers stamp `retrieved_at`

**Files:**
- Modify: `packs/cars/pipeline/ledger/export.py:363-374`
- Modify: `packs/cars/build.py:608-628`
- Modify: `src/app/mcp_server.py:352-366`
- Test: `src/app/tests/test_mcp_server.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: a `retrieved_at` key on each dict in a claim's `sources` list, carried from the ledger through the pack builder into `sources.retrieved_at`.

### Why this is in this plan

The fourth signal is currently unwritable. All 193 `sources` rows in the live store have `retrieved_at = ''` because **all three producers hardcode the empty string** — the ledger exporter never selects `documents.fetched_at`, the cars builder passes `""`, and `submit_findings` passes `""`. Shipping a health page with a permanently blank staleness column would be shipping a dead instrument. The fix is derivable at every step (automation principle: no human in the data path) and backfills nothing — the legacy 193 stay blank and the tree reports them as unknown, which is the fail-open behaviour.

- [ ] **Step 1: Write the failing test**

Append to `src/app/tests/test_mcp_server.py`:

```python
def test_a_submitted_finding_records_when_it_was_retrieved(store):
    """An agent submitting a quote now *is* the retrieval.

    Nothing else can supply this date: the agent read the page during the call.
    Left empty — as it was until 2026-08-31 — the staleness signal in
    kriko.lookup.tree is permanently blank and the health view ships a dead
    column.
    """
    from kriko.store.db import connect

    mcp_server.submit_findings(
        subject_id=_subject(),
        pack_id="tools",
        findings=[{
            "title": "Chuck jaws slip under load",
            "rationale": "Reported repeatedly on the 18V platform above 400 hours.",
            "domain": "mech",
            "component": "chuck",
            "severity": "high",
            "quote": "The chuck lost grip on a 10mm bit within a year.",
            "source_url": "https://forum.example.org/thread/1",
        }],
    )
    conn = connect(store)
    retrieved = conn.execute(
        "SELECT retrieved_at FROM sources WHERE url = ?",
        ("https://forum.example.org/thread/1",),
    ).fetchone()[0]
    conn.close()
    assert retrieved, "submit_findings must stamp retrieved_at"
    assert retrieved.startswith("20")
```

Also append to `src/kriko/tests/test_pack_build.py` (find the existing evidence test for the surrounding style):

```python
def test_a_sources_retrieval_date_survives_the_build(tmp_path):
    """`retrieved_at` in the YAML must reach sources.retrieved_at."""
    # Build a pack whose one claim carries `retrieved_at: "2026-08-01"` on its
    # evidence, using this file's existing _pack helper, then:
    #   SELECT retrieved_at FROM sources
    # and assert it is "2026-08-01", not "".
```

Replace that comment with the real assertion, mirroring the file's existing helper — `kriko/pack/build.py:372` already reads `ev.get("retrieved_at", "")`, so this test may pass immediately. If it does, say so in the task report and keep the test: it is the regression guard for the pack-level contract that Tasks 2's other two edits feed.

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest -o addopts="" -q \
  src/app/tests/test_mcp_server.py::test_a_submitted_finding_records_when_it_was_retrieved
```

Expected: FAIL — `AssertionError: submit_findings must stamp retrieved_at`.

- [ ] **Step 3: Fix the three producers**

In `src/app/mcp_server.py`, the `INSERT OR IGNORE INTO sources` at line ~352 passes `""` for both dates. Add near the top of the module (check whether `datetime` is already imported):

```python
from datetime import datetime, timezone
```

and replace the `retrieved_at` argument (the last of the ten) with:

```python
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
```

Leave `published_at` as `""` — the agent does not know when the page was written, and guessing it would be inventing data.

In `packs/cars/pipeline/ledger/export.py`, the sources comprehension at line ~363 selects `d.url, d.site_or_channel, e.quote`. `documents` also has a `fetched_at` column, which is exactly this date. Change the SELECT and the dict:

```python
        sources = [
            {"source_url": s["url"],
             "source_domain": (urlparse(s["url"]).netloc.removeprefix("www.")
                               if s["url"].startswith("http")
                               else (s["site_or_channel"] or "")),
             "site_or_channel": s["site_or_channel"],
             # When we last actually saw the page. Feeds sources.retrieved_at
             # and, through it, the staleness signal in kriko.lookup.tree.
             "retrieved_at": s["fetched_at"] or "",
             "quote": s["quote"], "independent": True}
            for s in conn.execute(
                "SELECT DISTINCT d.url, d.site_or_channel, d.fetched_at, e.quote"
                " FROM cluster_members m JOIN evidence e ON e.id=m.evidence_id"
                " JOIN documents d ON d.id=e.doc_id WHERE m.cluster_id=?"
                " ORDER BY d.url", (row["id"],))
        ]
```

In `packs/cars/build.py`, `_emit_claim_evidence` passes `""` for both dates. Replace the last two positional arguments of the `sources` insert with:

```python
                source.get("published_at", ""),
                source.get("retrieved_at", ""),
```

Note the committed YAMLs under `packs/cars/data/` carry no `retrieved_at`, so the 193 existing sources stay blank. That is correct: no backfill, no invented dates, and the tree reports them as unknown rather than as stale.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest -o addopts="" -q
```

Expected: full suite green. `src/app/pipeline/tests/test_ledger_run.py` exercises the exporter — if it fails on `fetched_at`, check the column name against `packs/cars/pipeline/ledger/ledger.db` (`pragma table_info(documents)`).

- [ ] **Step 5: Commit**

```bash
git add packs/cars/pipeline/ledger/export.py packs/cars/build.py \
        src/app/mcp_server.py src/app/tests/test_mcp_server.py \
        src/kriko/tests/test_pack_build.py
git commit -m "fix(evidence): record when we actually saw the page"
```

---

## Task 3: The HTTP router — `app/web/routers/health.py`

**Files:**
- Create: `src/app/web/routers/health.py`
- Modify: `src/app/web/app.py:22` (import) and `:33-39` (router tuple)
- Test: `src/app/tests/test_web.py`

**Interfaces:**
- Consumes: `kriko.lookup.tree.weakest_claims(conn, pack_ids=None, limit)`, `kriko.lookup.tree.subject_tree(conn, subject_id, pack_ids=None)`, and their dataclasses exactly as defined in Task 1.
- Produces, relied on by Task 4:
  - `GET /api/health/weakest?limit=20&pack_id=` → `{"claims": [ …ClaimHealth as dict, plus "concern": [int,int,float,str] ]}`
  - `GET /api/health/subject/{subject_id}` → `{"subject_id", "label", "pack_ids": [...], "claims": [{"health": {...}, "evidence": [{...}]}]}`

**Naming note:** `app.py` already defines `GET /api/health` inline as the liveness probe. The new router uses `prefix="/api/health"` with routes `/weakest` and `/subject/{subject_id}`, which does not collide — but register the router **after** the inline route exists and verify with the test in Step 2 that `GET /api/health` still returns `{"ok": true, ...}`.

- [ ] **Step 1: Write the failing tests**

Append to `src/app/tests/test_web.py`. The file's `client` fixture builds an app over a temporary store with the `PACK` fixture already defined there; check whether that pack's claims carry evidence and add a refuting source to one of them if not — the ordering test needs one.

```python
def test_the_liveness_probe_still_answers_after_the_health_router(client):
    """`/api/health` is the probe; `/api/health/weakest` is the new view."""
    assert client.get("/api/health").json()["ok"] is True


def test_the_weakest_endpoint_lists_claims_worst_first(client):
    body = client.get("/api/health/weakest").json()
    assert body["claims"]
    concerns = [tuple(c["concern"]) for c in body["claims"]]
    assert concerns == sorted(concerns)


def test_the_weakest_endpoint_reports_each_signal_separately(client):
    claim = client.get("/api/health/weakest").json()["claims"][0]
    for field in ("refuted_by", "independent_sources", "best_tier",
                  "best_trust", "oldest_retrieved_at", "newest_published_at"):
        assert field in claim


def test_the_weakest_endpoint_honours_the_limit(client):
    body = client.get("/api/health/weakest?limit=1").json()
    assert len(body["claims"]) <= 1


def test_the_weakest_endpoint_can_be_scoped_to_one_pack(client):
    body = client.get("/api/health/weakest?pack_id=tools").json()
    assert {c["pack_id"] for c in body["claims"]} <= {"tools"}


def test_the_subject_endpoint_returns_the_tree_with_its_evidence(client):
    subject = client.get("/api/subjects").json()[0]["subject_id"]
    body = client.get(f"/api/health/subject/{subject}").json()
    assert body["subject_id"] == subject
    assert body["claims"]
    assert "evidence" in body["claims"][0]
    assert "health" in body["claims"][0]


def test_an_unknown_subject_is_an_empty_tree_not_a_500(client):
    body = client.get("/api/health/subject/nope").json()
    assert body["claims"] == []


def test_the_health_view_never_writes(client):
    """Read-only by contract. If this view can mutate, it is not observability."""
    before = client.get("/api/health/weakest").json()
    client.get("/api/health/weakest")
    assert client.get("/api/health/weakest").json() == before
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
.venv/bin/python -m pytest -o addopts="" -q src/app/tests/test_web.py -k health
```

Expected: 404s — `assert body["claims"]` fails with a `KeyError`, or the response is `{"detail": "Not Found"}`.

- [ ] **Step 3: Write the router and register it**

Create `src/app/web/routers/health.py`:

```python
"""How well supported is what we ship?

The other side of the coverage report. `/api/packs/{id}/gaps` answers absence
— subjects nobody has researched. This answers weakness — claims that are
shipped on one forum post, or that we hold a rebuttal to. Both are needed: a
researcher with no weakness view can only ever add, never repair.

Read-only, and deliberately so. Nothing here writes, and no ranking the reader
sees is changed by it.
"""

from dataclasses import asdict

from fastapi import APIRouter, Depends

from app.web.deps import get_store
from kriko.lookup.tree import subject_tree, weakest_claims

router = APIRouter(prefix="/api/health", tags=["health"])


def _health(health) -> dict:
    """A ClaimHealth as JSON, with its sort key alongside.

    `concern` travels with the row on purpose: the order is only defensible if
    the reader can see what produced it.
    """
    return {**asdict(health), "concern": list(health.concern)}


@router.get("/weakest")
def weakest(limit: int = 20, pack_id: str = "", store=Depends(get_store)):
    packs = [pack_id] if pack_id else None
    return {"claims": [_health(h)
                       for h in weakest_claims(store, packs, limit=limit)]}


@router.get("/subject/{subject_id}")
def subject(subject_id: str, store=Depends(get_store)):
    """An unknown subject is an empty tree, not a 404.

    Unlike `/api/subjects/{id}`, which 404s because the caller asked for a
    thing that does not exist, this endpoint answers a question about health —
    and "nothing known" is a valid answer to it.
    """
    tree = subject_tree(store, subject_id)
    return {
        "subject_id": tree.subject_id,
        "label": tree.label,
        "pack_ids": list(tree.pack_ids),
        "claims": [
            {"health": _health(node.health),
             "evidence": [asdict(row) for row in node.evidence]}
            for node in tree.claims
        ],
    }
```

In `src/app/web/app.py`, extend the import at line 22 and the tuple:

```python
from app.web.routers import analyze, control, health, packs, query, subjects
```

```python
    for router in (
        packs.router,
        query.router,
        subjects.router,
        analyze.router,
        control.router,
        health.router,
    ):
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest -o addopts="" -q src/app/tests/test_web.py
.venv/bin/python -m pytest -o addopts="" -q
```

Expected: both green.

- [ ] **Step 5: Commit**

```bash
git add src/app/web/routers/health.py src/app/web/app.py src/app/tests/test_web.py
git commit -m "feat(web): serve claim health — weakest first, signals separate"
```

---

## Task 4: The MCP tool — an agent reads back what it wrote

**Files:**
- Modify: `src/app/mcp_server.py` (add one `@mcp.tool()` beside `coverage_gaps` at line ~233)
- Test: `src/app/tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `kriko.lookup.tree.subject_tree`, `kriko.lookup.tree.weakest_claims`, and the router's JSON shape from Task 3 — return the **same** structure so an agent and the dashboard cannot be told apart.
- Produces: `subject_health(subject_id: str, pack_id: str = "") -> dict` and `weakest_claims(pack_id: str = "", limit: int = 20) -> list[dict]`.

**Naming note:** the tool is named `subject_health`, not `subject_tree`, because a tool called `subject_tree` sits confusingly next to the existing `get_subject` and because the module-level import would shadow it. Import the engine functions under aliases:

```python
from kriko.lookup.tree import subject_tree as _subject_tree
from kriko.lookup.tree import weakest_claims as _weakest_claims
```

- [ ] **Step 1: Write the failing test**

Append to `src/app/tests/test_mcp_server.py`:

```python
def test_an_agent_can_read_back_the_evidence_shape_of_a_subject(store):
    """This is the whole point: an agent notices its own asymmetry.

    A finding it just submitted rests on one forum post. An existing claim
    rests on three specialist sources. Nothing before this could show it that.
    """
    tree = mcp_server.subject_health(subject_id=_subject())
    assert tree["subject_id"] == _subject()
    assert tree["claims"]
    node = tree["claims"][0]
    assert "concern" in node["health"]
    assert {"refuted_by", "independent_sources", "best_tier"} <= set(node["health"])


def test_the_weakest_tool_ranks_worst_first(store):
    rows = mcp_server.weakest_claims()
    concerns = [tuple(r["concern"]) for r in rows]
    assert concerns == sorted(concerns)


def test_an_unknown_subject_is_an_empty_tree_over_mcp(store):
    assert mcp_server.subject_health(subject_id="nope")["claims"] == []
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/bin/python -m pytest -o addopts="" -q src/app/tests/test_mcp_server.py -k health
```

Expected: `AttributeError: module 'app.mcp_server' has no attribute 'subject_health'`.

- [ ] **Step 3: Write the tools**

Add to `src/app/mcp_server.py`, immediately after `coverage_gaps` (which ends around line 255) so the two sit together as the two halves of the same question:

```python
@mcp.tool()
def subject_health(subject_id: str, pack_id: str = "") -> dict:
    """How well supported is everything we know about this subject?

    The read-back that lets an agent catch its own mistake. Each claim comes
    with four separate signals — how many sources refute it, how many
    independent sources support it, the best source's trust tier, and when we
    last saw the page — plus the evidence itself. No score: an agent that gets
    one number cannot tell a weak claim from an old one.

    `independent` and `stance` are flags whoever wrote the evidence supplied.
    They are assertions about the sources, not verified facts.
    """
    packs = [pack_id] if pack_id else None
    with _store() as conn:
        tree = _subject_tree(conn, subject_id, packs)
        return {
            "subject_id": tree.subject_id,
            "label": tree.label,
            "pack_ids": list(tree.pack_ids),
            "claims": [
                {"health": {**asdict(node.health),
                            "concern": list(node.health.concern)},
                 "evidence": [asdict(row) for row in node.evidence]}
                for node in tree.claims
            ],
        }


@mcp.tool()
def weakest_claims(pack_id: str = "", limit: int = 20) -> list[dict]:
    """The shipped claims that are least well supported, worst first.

    `coverage_gaps` answers what is missing; this answers what is thin. A
    claim with no sources at all appears in neither — it is not weak evidence,
    it is no evidence, and it belongs to the coverage report.
    """
    packs = [pack_id] if pack_id else None
    with _store() as conn:
        return [{**asdict(h), "concern": list(h.concern)}
                for h in _weakest_claims(conn, packs, limit=limit)]
```

Add the imports at the top of the module:

```python
from dataclasses import asdict

from kriko.lookup.tree import subject_tree as _subject_tree
from kriko.lookup.tree import weakest_claims as _weakest_claims
```

Check whether `asdict` is already imported before adding it.

- [ ] **Step 4: Run the tests to verify they pass**

```bash
.venv/bin/python -m pytest -o addopts="" -q
```

- [ ] **Step 5: Commit**

```bash
git add src/app/mcp_server.py src/app/tests/test_mcp_server.py
git commit -m "feat(mcp): let an agent read back how well sourced its claims are"
```

---

## Task 5: The Health tab in the dashboard

**Files:**
- Modify: `src/app/web/static/index.html` — nav button (after the `coverage` tab, line ~16) and a `<section id="health">` (after the `coverage` section, line ~88-91)
- Modify: `src/app/web/static/app.js` — `renderHealth()` and one line in the tab handler (line ~305-318)
- Modify: `src/app/web/static/app.css` — `.concern`, `.signal`, `.stale`

### Background the implementer needs

The dashboard is a **vanilla JS single-page app**, not server-rendered templates. `index.html` (117 lines) holds one `<section>` per tab; `app.js` (342 lines) has one `render*()` per tab, wired in a single `$$(".tab").forEach(...)` handler at the bottom. Follow that shape exactly — no framework, no build step, ES module, and every interpolated value goes through the file's existing `esc()`. Existing CSS classes to reuse: `.card`, `.badge`, `.meta`, `.state`, `.empty`, `.sev`, `td.num`, `blockquote.refutes`.

- [ ] **Step 1: Add the tab and its section**

In `index.html`, after the Coverage nav button:

```html
        <button class="tab" data-tab="health">Health</button>
```

After the `<section id="coverage">` block:

```html
    <section id="health">
        <h2>Claim health</h2>
        <p class="meta">
            The weakest-supported claims we ship, worst first. Contradicted,
            then fewest independent sources, then weakest best source, then
            stalest. No combined score — each signal is its own column.
            <em>Independence and stance are flags the pack author supplied,
            not verified facts.</em>
        </p>
        <div id="health-list"></div>
    </section>
```

- [ ] **Step 2: Add `renderHealth()` to `app.js`**

Insert immediately after `renderCoverage()` (which ends around line 205):

```javascript
const SIGNAL_NOTE = {
    refuted: "a source in the pack contradicts this claim",
    thin: "only one independent source supports this",
    weak: "the best supporting source is a low-trust tier",
};

function healthRow(claim) {
    const refuted = claim.refuted_by > 0;
    const stale = claim.oldest_retrieved_at || "unknown";
    const note = refuted
        ? SIGNAL_NOTE.refuted
        : claim.independent_sources <= 1
          ? SIGNAL_NOTE.thin
          : claim.best_trust < 0.5
            ? SIGNAL_NOTE.weak
            : "";
    return `<tr class="${refuted ? "concern" : ""}">
        <td>${esc(claim.title)}<div class="meta">${esc(claim.subject_label)} · ${esc(claim.pack_id)}</div>${note ? `<div class="meta">${esc(note)}</div>` : ""}</td>
        <td class="num signal">${refuted ? `<span class="badge">${claim.refuted_by} refuting</span>` : "—"}</td>
        <td class="num signal">${claim.independent_sources}</td>
        <td class="signal">${esc(claim.best_tier)} <span class="meta">${claim.best_trust.toFixed(2)}</span></td>
        <td class="signal ${claim.oldest_retrieved_at ? "" : "stale"}">${esc(stale)}</td>
        <td><button data-tree="${esc(claim.subject_id)}">Evidence</button></td>
    </tr>`;
}

async function renderHealth() {
    const target = $("#health-list");
    try {
        const { claims } = await api("/api/health/weakest?limit=40");
        if (!claims.length) {
            target.innerHTML = `<p class="state empty">No sourced claims installed yet.</p>`;
            return;
        }
        target.innerHTML = `<table><thead><tr>
                <th>Claim</th><th>Contradicted</th><th>Independent sources</th>
                <th>Best source</th><th>Last retrieved</th><th></th>
            </tr></thead><tbody>${claims.map(healthRow).join("")}</tbody></table>
            <div id="health-tree"></div>`;
        $$("[data-tree]", target).forEach((button) =>
            button.addEventListener("click", () =>
                renderHealthTree(button.dataset.tree),
            ),
        );
    } catch (error) {
        showError("#health-list", error);
    }
}

async function renderHealthTree(subjectId) {
    const target = $("#health-tree");
    try {
        const tree = await api(
            `/api/health/subject/${encodeURIComponent(subjectId)}`,
        );
        target.innerHTML = `<article class="card"><h3>${esc(tree.label || subjectId)} <span class="badge">${tree.claims.length} claim(s)</span></h3>${tree.claims
            .map(
                ({ health, evidence }) =>
                    `<details><summary>${esc(health.title)} <span class="meta">${health.independent_sources} source(s) · ${esc(health.best_tier)}</span></summary>${evidence.length ? evidence.map((row) => `<blockquote class="${row.stance === "refutes" ? "refutes" : ""}">${esc(row.quote)}<footer class="meta">${esc(row.domain)} · ${esc(row.tier)} · ${esc(row.stance)}${row.independent ? "" : " · not independent"} · retrieved ${esc(row.retrieved_at || "unknown")}</footer></blockquote>`).join("") : `<p class="state empty">No sources — this claim rests on an interval or a rule, not a citation.</p>`}</details>`,
            )
            .join("")}</article>`;
    } catch (error) {
        showError("#health-tree", error);
    }
}
```

In the tab handler at the bottom, beside the existing `if` lines:

```javascript
        if (tab.dataset.tab === "health") renderHealth();
```

- [ ] **Step 3: Add the CSS**

Append to `app.css`, matching the file's existing terse style:

```css
tr.concern td { border-left: 3px solid #b3261e; }
.signal { white-space: nowrap; }
.stale { opacity: 0.55; font-style: italic; }
```

- [ ] **Step 4: Verify it renders against real data**

```bash
.venv/bin/python -m app.cli build packs/cars
.venv/bin/python -m app.cli install dist/cars.kpack
.venv/bin/python -m app.web &
sleep 3
curl -s "http://127.0.0.1:8787/api/health/weakest?limit=3" | head -c 800
```

Expected: three claims with `concern` arrays in ascending order and non-empty `best_tier`. Then open `http://127.0.0.1:8787/`, click **Health**, and confirm: rows appear worst-first, the "Last retrieved" column reads `unknown` in muted italic (correct — the 193 legacy sources have no date and Task 2 backfills nothing), and clicking **Evidence** expands the quotes. Kill the server afterwards.

Report the actual top three claim titles and their signal values in the task report. If the table is empty while `/api/health/weakest` returns claims, the bug is in the JS, not the API.

- [ ] **Step 5: Commit**

```bash
git add src/app/web/static/
git commit -m "feat(web): a Health tab — see which claims are thinly sourced"
```

---

## Task 6: Docs, backlog, and end-to-end verification

**Files:**
- Modify: `docs/ARCHITECTURE.md` — add `lookup/tree.py` to the reading map and to the "Chasing X?" index
- Modify: `docs/INTERNALS.md` — a short section on the four signals and the lexicographic ordering
- Modify: `README.md` — one line under the dashboard description mentioning the Health tab
- Modify: `backlog.md` / `done.md`

- [ ] **Step 1: Update the docs**

In `docs/ARCHITECTURE.md`, add a row to whichever table lists `src/kriko/lookup/` modules:

> `lookup/tree.py` — the same rows `rank.py` scores, read the other way: how well supported is each claim? Four separate signals, lexicographic ordering, no score.

And to the "Chasing X? read these" index:

> **Why is this claim ranked so low / who says so?** → `src/kriko/lookup/tree.py`, then `src/app/web/routers/health.py`.

In `docs/INTERNALS.md`, add a section under the lookup material:

```markdown
### Claim health — reading the evidence back out

`kriko/lookup/tree.py` answers the question the serving path cannot: *how well
supported is what we ship?* Four signals, never combined into a score —
contradiction (`evidence.stance = 'refutes'`), corroboration (distinct
independent supporting sources), the best source's trust tier, and staleness
(`sources.retrieved_at`).

Ordering is lexicographic and ascending on every element, exposed as
`ClaimHealth.concern`, so the order is inspectable rather than implied by a
weight nobody can justify. Two deliberate asymmetries:

- **A claim with no evidence is not weak, it is uncovered.** It is excluded
  from `weakest_claims()` and reported by the coverage report instead, matching
  `rank.py`'s treatment of source-free interval claims as trust-neutral.
- **An absent `retrieved_at` sorts LAST, not first.** No timestamp is not
  evidence of staleness. Before 2026-08-31 all three producers wrote `''`
  here; they now derive it (`documents.fetched_at` in the ledger, the
  submission time over MCP), and legacy rows stay honestly blank.
```

In `README.md`, extend the dashboard line with the Health tab.

- [ ] **Step 2: Update the task tracking**

Move the knowledge-tree item into `done.md` with today's date (2026-08-31) and the commit range, and add these follow-ups to `backlog.md`, each one line with its evidence:

- **B45** — `sources.published_at` is written by nobody. The ledger has no publication-date extractor, so the tree reports it always empty. Derive it from page metadata during ingest, or drop the column.
- **B46** — `evidence.independent` is `1` on all 719 rows; nothing ever computes independence. Until it does, "independent sources" means "distinct sources", and the health view says so. Deriving it (same domain, same syndicated text, same author) is the real fix.
- **B47** — no producer emits `stance = 'refutes'`, so the sharpest signal in the health view has zero live hits. The verdict step already sees contradicting evidence within a cluster; it should record the rebuttal rather than discarding it.
- **B48** — feed observed weakness back into `relevance()`. Deliberately out of scope here (spec non-goal), but a claim with one forum source ranking beside one with three bulletins is a ranking question, not only a reporting one.

- [ ] **Step 3: Run the whole suite and the layering guards**

```bash
.venv/bin/python -m pytest -o addopts="" -q
grep -rnE "^[[:space:]]*(from|import) (backend|app|packs|knowledge)" --include='*.py' src/kriko/ | grep -v /tests/
grep -rnE "^[[:space:]]*(from|import) (backend|app|packs)" --include='*.py' packs/cars/pipeline/ | grep -v /tests/
```

Expected: suite green with no failures; both greps print nothing.

- [ ] **Step 4: End-to-end verification against the real store**

```bash
.venv/bin/python -m app.cli build packs/cars
.venv/bin/python -m app.cli install dist/cars.kpack
.venv/bin/python -m app.cli lookup --help | head -5
.venv/bin/python - <<'EOF'
from kriko.lookup.tree import weakest_claims, subject_tree
from kriko.store.db import connect, DEFAULT_STORE
conn = connect(DEFAULT_STORE)
rows = weakest_claims(conn, limit=5)
for r in rows:
    print(f"{r.concern}  {r.title[:60]!r}  {r.subject_label[:30]!r}")
print("subjects with a tree:", len(subject_tree(conn, rows[0].subject_id).claims))
EOF
```

Report the actual output in the task report — specifically whether the top rows are genuinely the thinly-sourced ones and whether `best_tier` varies (a column that is constant means tier resolution is not reaching the pack's `source_tiers` rows).

- [ ] **Step 5: Commit and push**

```bash
git add docs/ARCHITECTURE.md docs/INTERNALS.md README.md backlog.md done.md
git commit -m "docs: how claim health is computed, and what it cannot yet see"
git push -u origin feat/knowledge-engine-pivot
```

---

## Self-Review

**Spec coverage:** `tree.py` with both entry points → Task 1. Reuse of `rank.py`'s tier resolution → Task 1, asserted by `test_the_tree_and_rank_agree_on_every_tier`. Lexicographic ordering with no scalar, `concern` exposed → Task 1. Two routes on `/api/health` → Task 3. The rendered page → Task 5. The MCP tool → Task 4. Every test the spec's Testing section names (ordering, two packs, empty store, category-free) → Task 1 and Task 3. Verification section → Tasks 5 and 6. Every risk in the spec's table has either a test (tier drift, arbitrary ordering) or an explicit non-goal restated (scope creep into scoring, Task 6's B48).

**Spec deviations, all deliberate:**
1. `pack_ids` defaults to `None` → enabled packs, rather than being required. Three callers would otherwise repeat `enabled_pack_ids(conn)`; `lookup()` already does exactly this.
2. Claims with zero evidence are excluded from `weakest_claims()`. The spec did not say, and the live store's 6 unsourced claims plus `rank.py`'s explicit trust-neutral treatment of source-free interval claims make excluding them correct — absence is the coverage report's question.
3. Unknown `retrieved_at` sorts **last**, not first. Forced by the live data: all 193 sources are blank, so the alternative ranks the whole catalog by a signal carrying no information.
4. Task 2 is new — not in the spec, but the spec's fourth signal is unwritable without it.
5. The MCP tool is `subject_health`, not `subject_tree`, to avoid shadowing the imported function and colliding conceptually with `get_subject`.

**Placeholder scan:** one intentional stub remains — the second test in Task 2 Step 1 asks the implementer to write the assertion against the existing `_pack` helper in `test_pack_build.py`, because that helper's signature is local to that file and inventing it here would be worse than naming it. Every other code block is complete.

**Type consistency:** `ClaimHealth` field names are identical in Task 1's dataclass, Task 3's `asdict` serialisation, Task 4's tool and Task 5's `healthRow()` (`refuted_by`, `independent_sources`, `best_tier`, `best_trust`, `oldest_retrieved_at`, `subject_label`, `pack_id`, `subject_id`, `title`). `concern` is a 4-tuple in Python and a 4-element array in JSON everywhere. `EvidenceRow` fields match between `asdict` and the JS (`quote`, `domain`, `tier`, `stance`, `independent`, `retrieved_at`). Task 3's response shape (`{"health": …, "evidence": […]}`) is what Task 4 returns and what Task 5's `renderHealthTree()` destructures.
