"""The MCP tools — the $0 research plane.

The handlers are plain functions; FastMCP registers them without wrapping, so
these tests exercise exactly the code an agent calls.

Almost every assertion here is about one thing: an agent may not put a quote
into the evidence chain that it did not actually read. Everything else the
server does is a query.
"""

import textwrap

import pytest

from app import mcp_server
from kriko.pack import build
from kriko.store import ids, packstore

PACK = {
    "toml": """
        [pack]
        id = "tools"
        name = "Tools"
        version = "0.1.0"
        [identity]
        product = ["brand", "model"]
    """,
    "terms": """
        - {term_id: product, role: subject_kind}
        - {term_id: brand, role: attribute, datatype: text, match: {required: true}}
        - {term_id: model, role: attribute, datatype: text, match: {required: true}}
        - {term_id: usage_hours, role: context_key, datatype: number, unit: hours}
        - {term_id: mech, role: domain}
    """,
    "subjects": """
        - kind: product
          label: Makita DHP484
          identity: {brand: makita, model: DHP484}
        - kind: product
          label: Unresearched Thing
          identity: {brand: acme, model: nothing}
    """,
    "claims": """
        - subject: {kind: product, identity: {brand: makita, model: DHP484}}
          kind: known_issue
          domain: mech
          severity: high
          text: {en: {title: Chuck slips under torque, body: b, advice: a}}
    """,
    "principle": "Keep only what handling the tool would not reveal.",
    "templates": '- "{alias} common faults"\n',
    "gates": """
        noise:
            - { pattern: '\\bwarning\\s+light\\b', note: true of any tool }
        covered:
            # A deliberately routine-sounding phrase that also happens to sit
            # in "DQ381 mechatronics failure from 120000 km" — present so the
            # config-specific test's DQ381 code / 120000 km mileage anchor is
            # load-bearing: without a declared specificity pattern to escape
            # it, this term alone would reject that finding as covered.
            - { pattern: mechatronics failure, note: stand-in routine phrase }
        specificity:
            - { pattern: '\\b[A-Za-z]{1,4}\\d[A-Za-z0-9]{0,3}\\b' }
            - { pattern: '\\b\\d[\\d,.]*\\s*(km|kilomet|mile|mi)\\b' }
        limits:
            - { pattern: max_title_chars, note: "100" }
            - { pattern: min_rationale_chars, note: "60" }
    """,
}


@pytest.fixture
def store(tmp_path, monkeypatch):
    root = tmp_path / "p"
    (root / "vocabulary").mkdir(parents=True)
    (root / "data").mkdir(parents=True)
    (root / "research").mkdir(parents=True)
    (root / "pack.toml").write_text(textwrap.dedent(PACK["toml"]), encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(
        textwrap.dedent(PACK["terms"]), encoding="utf-8"
    )
    (root / "data" / "subjects.yaml").write_text(
        textwrap.dedent(PACK["subjects"]), encoding="utf-8"
    )
    (root / "data" / "claims.yaml").write_text(
        textwrap.dedent(PACK["claims"]), encoding="utf-8"
    )
    (root / "research" / "principle.md").write_text(PACK["principle"], encoding="utf-8")
    (root / "research" / "templates.yaml").write_text(
        PACK["templates"], encoding="utf-8"
    )
    (root / "vocabulary" / "gates.yaml").write_text(
        textwrap.dedent(PACK["gates"]), encoding="utf-8"
    )

    path = tmp_path / "store.sqlite"
    # Never touch the real ~/.kriko during tests.
    monkeypatch.setattr(mcp_server, "STORE_PATH", path)
    from kriko.store.db import connect

    conn = connect(path)
    packstore.install(conn, build.build(root, tmp_path / "p.kpack"))
    conn.close()
    return path


def _subject(label="Makita DHP484"):
    return (
        ids.subject_id("product", {"brand": "makita", "model": "DHP484"})
        if label == "Makita DHP484"
        else ids.subject_id("product", {"brand": "acme", "model": "nothing"})
    )


# ── reads ────────────────────────────────────────────────────────────────


def test_list_packs_reports_state(store):
    (pack,) = mcp_server.list_packs()
    assert pack["pack_id"] == "tools"
    assert pack["enabled"] is True


def test_store_status_counts_rows(store):
    status = mcp_server.store_status()
    assert status["subjects"] == 2
    assert status["claims"] == 1


def test_list_subjects_orders_by_how_much_is_known(store):
    subjects = mcp_server.list_subjects()
    assert subjects[0]["label"] == "Makita DHP484"
    assert subjects[0]["claims"] == 1


def test_get_subject_returns_its_attributes_and_claims(store):
    got = mcp_server.get_subject(_subject())
    assert got["attributes"]["brand"] == "makita"
    assert got["claims"][0]["title"] == "Chuck slips under torque"


def test_get_subject_is_an_answer_not_an_exception_when_absent(store):
    assert "error" in mcp_server.get_subject("nope")


def test_lookup_matches_the_cli(store):
    got = mcp_server.lookup("product", {"brand": "makita", "model": "DHP484"})
    assert got["method"] == "exact"
    assert got["claims"][0]["title"] == "Chuck slips under torque"


def test_the_brief_carries_the_packs_own_principle(store):
    brief = mcp_server.research_brief(_subject(), "tools")
    assert "Keep only what handling the tool would not reveal." in brief["brief"]
    assert "Makita DHP484 common faults" in brief["queries"]


def test_coverage_gaps_finds_the_unresearched_subject(store):
    """Fail-open made findable: a gap is not an error, but it must be visible."""
    gaps = mcp_server.coverage_gaps()
    assert [g["label"] for g in gaps] == ["Unresearched Thing"]


# ── writes, and the grounding rule ───────────────────────────────────────


def test_a_warning_light_finding_is_refused_by_the_packs_own_gate(store):
    """The product principle is enforced at write time, not requested in a prompt.

    The pack's own vocabulary/gates.yaml declares dashboard-warning-light
    language under `noise`. A finding matching it must not become evidence, and
    the agent must be told which rule refused it — a prompt asks, a gate
    decides.
    """
    result = mcp_server.submit_findings(_subject(), "tools", [{
        "title": "ABS warning light illuminates",
        "rationale": "The ABS light can come on and should be investigated by a mechanic.",
        "quote": "the ABS warning light illuminates",
        "document_text": "Owners report the ABS warning light illuminates.",
        "source_url": "https://example.test/a",
    }])
    assert result["accepted"] == []
    assert result["rejected"][0]["reason"] == "noise"


def test_a_config_specific_finding_still_lands(store):
    """The gate must not swallow what Kriko exists to surface."""
    result = mcp_server.submit_findings(_subject(), "tools", [{
        "title": "DQ381 mechatronics failure from 120000 km",
        "rationale": "The mechatronics unit is a documented weak point on this "
                     "gearbox and replacement is expensive.",
        "quote": "DQ381 mechatronics failure",
        "document_text": "Reports of DQ381 mechatronics failure are common.",
        "source_url": "https://example.test/b",
    }])
    assert result["rejected"] == []
    assert len(result["accepted"]) == 1


def test_the_documented_contract_is_actually_sufficient(store):
    """submit_findings' own docstring must not describe a shape the gate refuses.

    The docstring says a finding with no code/mileage in its own text still
    survives if `component` names the concrete part — that a caller can
    satisfy the anchor requirement with the field instead of the wording.
    This finding is exactly that shape and nothing else: no engine/gearbox
    code, no mileage figure, generic-sounding failure language, just a
    `component`. If a future change to the gate or the docstring lets the two
    disagree, this is the test that catches it.
    """
    document = (
        "Continuous heavy-load drilling overheats the front bearing, which "
        "then seizes and locks the chuck in place."
    )
    result = mcp_server.submit_findings(_subject(), "tools", [{
        "title": "Chuck bearing seizes under heavy load",
        "rationale": "Continuous heavy-load drilling overheats the front "
                     "bearing, which then seizes and locks the chuck, "
                     "requiring a full bearing replacement.",
        "quote": "seizes and locks the chuck in place",
        "document_text": document,
        "source_url": "https://example.test/c",
        "component": "front_bearing",
    }])
    assert result["rejected"] == []
    assert len(result["accepted"]) == 1


DOCUMENT = (
    "Owners report that the chuck jaws round off after heavy use "
    "and no longer grip smooth shanks."
)


def _finding(**kw):
    base = dict(
        title="Chuck jaws round off",
        domain="mech",
        severity="medium",
        rationale="Heavy use gradually rounds off the jaw teeth, so the chuck no "
        "longer grips smooth-shank bits securely and needs replacement.",
        quote="the chuck jaws round off after heavy use",
        document_text=DOCUMENT,
        source_url="https://e.example/x",
        # component_hint doubles as the has_anchor signal submit_findings reads
        # (see app/mcp_server.py). Real production findings name a concrete
        # part; these grounding-rule tests are not about the specificity
        # anchor rule, so carry one rather than leaning on title/rationale
        # text to satisfy the pack's own specificity patterns incidentally.
        component="chuck",
    )
    base.update(kw)
    return base


def test_a_grounded_finding_is_stored(store):
    result = mcp_server.submit_findings(_subject(), "tools", [_finding()])
    assert result["rejected"] == []
    assert len(result["accepted"]) == 1
    assert mcp_server.store_status()["claims"] == 2


def test_a_quote_absent_from_the_document_is_refused(store):
    """The rule the whole evidence chain rests on."""
    result = mcp_server.submit_findings(
        _subject(), "tools", [_finding(quote="the motor catches fire within a week")]
    )
    assert result["accepted"] == []
    assert "verbatim" in result["rejected"][0]["reason"]
    assert mcp_server.store_status()["claims"] == 1


def test_a_finding_with_no_document_text_is_refused(store):
    """ "Trust me" is not an evidence model.

    Without the source text there is nothing to check the quote against, so
    accepting it would mean the grounding rule is optional — and a rule that is
    optional under pressure is not a rule.
    """
    result = mcp_server.submit_findings(
        _subject(), "tools", [_finding(document_text="")]
    )
    assert result["accepted"] == []
    assert "cannot be checked" in result["rejected"][0]["reason"]


def test_rejections_explain_themselves_per_finding(store):
    """An agent must learn which quotes failed, not lose half its work silently."""
    result = mcp_server.submit_findings(
        _subject(),
        "tools",
        [
            _finding(),
            _finding(title="", quote="the chuck jaws round off after heavy use"),
            _finding(quote=""),
        ],
    )
    assert len(result["accepted"]) == 1
    assert {r["reason"] for r in result["rejected"]} == {"no title", "no quote"}


def test_agent_written_claims_rank_as_reported_not_confirmed(store):
    """A subscription agent is a source, not an authority."""
    mcp_server.submit_findings(_subject(), "tools", [_finding()])
    from kriko.store.db import connect

    conn = connect(store)
    confidences = [
        r[0]
        for r in conn.execute(
            "SELECT author_confidence FROM claims WHERE author_confidence < 1.0"
        )
    ]
    conn.close()
    assert confidences and max(confidences) <= 0.6


def test_submitting_against_an_unknown_subject_is_an_answer_not_a_crash(store):
    assert "error" in mcp_server.submit_findings("nope", "tools", [_finding()])


def test_disabling_a_pack_hides_it_from_every_read(store):
    mcp_server.set_pack_enabled("tools", False)
    assert mcp_server.list_subjects() == []
    assert mcp_server.lookup("product", {"brand": "makita"})["method"] == "no_match"


def test_no_tool_reaches_into_a_pack_for_python():
    """Packs ship data. The MCP process never imports pack code.

    Tools are registered by a decorator at import time, so a pack supplying its
    own tools would mean importing pack Python here — the same door the browser
    extension keeps shut, for the same reason.
    """
    source = mcp_server.__file__
    text = open(source, encoding="utf-8").read()
    assert "import packs" not in text
    assert "from packs" not in text
