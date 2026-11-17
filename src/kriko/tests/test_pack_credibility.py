"""Where a claim's evidence comes from, and what that is worth.

The owner's rule is the one under test: AI-written prose is fine, but a claim
has to come from a source that stands behind it. These tests are the three
rules, plus the tier function they are made of, plus the fact that the tier
reaches the built pack rather than staying a comment.
"""

import json
import textwrap

import pytest

from kriko.pack import build, credibility
from kriko.store.db import connect

PACK_TOML = """
[pack]
id = "org.kriko.demo"
name = "Demo products"
version = "0.1.0"
license = "CC-BY-SA-4.0"
publisher = "kriko"

[identity]
product = ["brand", "model"]
"""

TERMS = """
- term_id: brand
  role: attribute
  datatype: text
- term_id: model
  role: attribute
  datatype: text
- term_id: mechanical
  role: domain
- term_id: product
  role: subject_kind
"""

SUBJECTS = """
- kind: product
  label: Anker PowerCore 10000
  identity: {brand: Anker, model: A1263}
"""


def _claim(*, severity="medium", urls=("https://recalleurope.com/x",), title="A finding"):
    evidence = "\n".join(
        f"    - url: {url}\n      quote: a line that was read there" for url in urls)
    return textwrap.dedent(f"""
    - subject: {{kind: product, identity: {{brand: Anker, model: A1263}}}}
      kind: known_issue
      domain: mechanical
      severity: {severity}
      text:
        en:
          title: {title}
          body: A body.
      evidence:
    """) + evidence + "\n"


def _write(tmp_path, claims):
    root = tmp_path / "demo"
    (root / "vocabulary").mkdir(parents=True)
    (root / "data").mkdir(parents=True)
    (root / "pack.toml").write_text(PACK_TOML, encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(TERMS, encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text(SUBJECTS, encoding="utf-8")
    (root / "data" / "claims.yaml").write_text(claims, encoding="utf-8")
    return root


def _claims(*items):
    return "".join(items)


def _issues(report, rule):
    return [issue for issue in report.issues if issue.rule == rule]


# ── the tier function ────────────────────────────────────────────────────────


def test_a_recall_register_is_official():
    """The page a recall was announced on is the standard, so it is official."""
    assert credibility.tier("https://www.recalleurope.com/alert/123") == "official"
    assert credibility.tier("https://www.cpsc.gov/Recalls/2026/x") == "official"


def test_a_government_domain_is_official_in_any_country():
    assert credibility.tier("https://static.nhtsa.gov/odi/rcl/2026/x.pdf") == "official"
    assert credibility.tier("https://www.saglik.gov.tr/x") == "official"
    assert credibility.tier("https://ec.europa.eu/safety-gate/x") == "official"
    assert credibility.tier("https://rappel.conso.gouv.fr/x") == "official"


def test_a_manufacturer_speaking_about_its_own_product_is_official():
    """A maker's support page is the maker speaking; the brand decides."""
    assert credibility.tier("https://support.anker.com/article/1", "Anker") == "official"
    assert credibility.tier("https://www.anker.com/recall") == "unknown"
    assert credibility.tier("https://samsung-centrum.pl/x", "Samsung") == "unknown"


def test_a_forum_is_community_and_a_complaint_site_is_community():
    """A report is a person's account, not a measurement."""
    assert credibility.tier("https://www.reddit.com/r/x/comments/1") == "community"
    assert credibility.tier("https://forum.example-forum.com/thread") == "community"
    assert credibility.tier("https://www.sikayetvar.com/anker") == "community"
    assert credibility.tier("https://ch.trustpilot.com/review/x") == "community"


def test_a_marketplace_is_commercial():
    """A listing is the seller's claim, not evidence about the product."""
    assert credibility.tier("https://www.trendyol.com/x") == "commercial"
    assert credibility.tier("https://www.hepsiburada.com/x") == "commercial"
    assert credibility.tier("https://m.alza.cz/x") == "commercial"
    assert credibility.tier("https://www.amazon.co.jp/dp/X") == "commercial"


def test_press_is_named_rather_than_guessed():
    assert credibility.tier("https://www.rtings.com/headphones/reviews/x") == "press"


def test_a_blog_nobody_recognises_is_unknown_not_weak():
    """`unknown` is an absence of a rule; calling it weak would be a verdict."""
    assert credibility.tier("https://some-randomsite.example/page") == "unknown"
    assert credibility.tier("") == "unknown"


def test_a_content_farm_and_a_placeholder_are_weak():
    assert credibility.tier("https://example.com/x") == "weak"
    assert credibility.tier("https://deepwiki.com/x") == "weak"


# ── rule (a): high severity needs an official source ─────────────────────────


def test_a_high_claim_with_no_official_source_is_recorded_and_can_fail():
    """The default records it; the owner's switch makes it a failure."""
    claims = [{"severity": "high", "text": {"en": {"title": "T"}},
               "evidence": [{"url": "https://www.trendyol.com/x"}]}]
    lenient = credibility.judge("demo", claims)
    assert [i.rule for i in lenient.warnings] == ["high-without-official"]
    assert lenient.errors == []

    strict = credibility.judge("demo", claims, credibility.Policy(strict=True))
    assert [i.rule for i in strict.errors] == ["high-without-official"]
    with pytest.raises(credibility.CredibilityError, match="high-without-official"):
        credibility.enforce(strict)


def test_a_high_claim_backed_by_an_official_source_passes():
    claims = [{"severity": "high", "text": {"en": {"title": "T"}},
               "evidence": [{"url": "https://www.cpsc.gov/Recalls/2026/x"}]}]
    report = credibility.judge("demo", claims, credibility.Policy(strict=True))
    assert report.issues == []


# ── rule (b): nothing credible backs the words ───────────────────────────────


def test_a_claim_whose_sources_are_all_weak_or_unknown_is_recorded_and_can_fail():
    claims = [{"severity": "medium", "text": {"en": {"title": "T"}},
               "evidence": [{"url": "https://example.com/x"},
                            {"url": "https://some-randomsite.example/y"}]}]
    lenient = credibility.judge("demo", claims)
    assert [i.rule for i in lenient.warnings] == ["no-credible-source"]
    assert "example.com" in lenient.warnings[0].detail

    strict = credibility.judge("demo", claims, credibility.Policy(strict=True))
    assert [i.rule for i in strict.errors] == ["no-credible-source"]


def test_one_credible_source_is_enough_to_clear_rule_b():
    claims = [{"severity": "medium", "text": {"en": {"title": "T"}},
               "evidence": [{"url": "https://example.com/x"},
                            {"url": "https://www.rtings.com/x"}]}]
    report = credibility.judge("demo", claims, credibility.Policy(strict=True))
    assert report.issues == []


# ── rule (c): one owner report is an anecdote ────────────────────────────────


def test_community_only_needs_two_domains():
    one = [{"severity": "low", "text": {"en": {"title": "T"}},
            "evidence": [{"url": "https://www.reddit.com/r/x/comments/1"},
                         {"url": "https://www.reddit.com/r/x/comments/2"}]}]
    report = credibility.judge("demo", one)
    assert [i.rule for i in report.warnings] == ["single-community-domain"]
    assert report.errors == []

    two = [{"severity": "low", "text": {"en": {"title": "T"}},
            "evidence": [{"url": "https://www.reddit.com/r/x/comments/1"},
                         {"url": "https://www.sikayetvar.com/x"}]}]
    assert credibility.judge("demo", two).issues == []


def test_a_claim_with_no_evidence_is_a_proposal_and_is_left_alone():
    """The site and the phone already leave it out; it is not a finding."""
    report = credibility.judge("demo", [{"severity": "high", "text": {}}])
    assert report.claims == 1
    assert report.issues == []


# ── the tier reaches the pack ────────────────────────────────────────────────


def test_a_built_pack_tiers_every_source_and_records_the_summary(tmp_path):
    root = _write(tmp_path, _claims(
        _claim(urls=("https://www.cpsc.gov/Recalls/2026/x",
                     "https://www.reddit.com/r/x/comments/1")),
        _claim(severity="low", urls=("https://www.trendyol.com/x",), title="B")))
    out = build.build(root, tmp_path / "demo.kpack")

    conn = connect(out)
    try:
        tiers = dict(conn.execute("SELECT domain, source_tier FROM sources"))
        summary = json.loads(
            conn.execute("SELECT credibility_json FROM packs").fetchone()[0])
    finally:
        conn.close()

    assert tiers["cpsc.gov"] == "official"
    assert tiers["reddit.com"] == "community"
    assert tiers["trendyol.com"] == "commercial"
    assert summary["claims"] == 2
    assert summary["sources"]["official"] == 1
    assert summary["sources"]["community"] == 1


def test_a_strict_build_refuses_the_pack_and_leaves_no_file(tmp_path):
    root = _write(tmp_path, _claims(
        _claim(severity="high", urls=("https://www.reddit.com/r/x/comments/1",))))
    out = tmp_path / "demo.kpack"
    with pytest.raises(credibility.CredibilityError):
        build.build(root, out, strict=True)
    assert not out.exists()
