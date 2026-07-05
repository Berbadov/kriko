"""Tests for the title-similarity dedup in resolver.py."""

import pytest
from backend.core.resolver import (
    ClaimResult,
    _deduplicate_results,
    _best_in_cluster,
)
from backend.core.title_sim import title_similar, title_tokens
from backend.db.models import Claim


def _make_claim(claim_id: str, title: str, domain: str = "engine",
                severity: str = "medium", status: str = "verified",
                strength: str = "confirmed", confidence: float = 0.6,
                rationale: str = "Test rationale.",
                inspection_advice: str = "Test advice.") -> ClaimResult:
    claim = Claim(
        id=claim_id,
        claim_key=claim_id,
        version=1,
        is_current=True,
        title=title,
        domain=domain,
        severity=severity,
        confidence=confidence,
        rationale=rationale,
        inspection_advice=inspection_advice,
        status=status,
        kind="known_issue",
    )
    return ClaimResult(claim=claim, strength=strength)


# ── title_sim unit tests ─────────────────────────────────────────────────────

def test_title_tokens_empty():
    assert title_tokens("") == set()
    assert title_tokens("   ") == set()


def test_title_tokens_stopwords_removed():
    tokens = title_tokens("The timing belt on a car")
    assert "the" not in tokens
    assert "a" not in tokens
    assert "timing" in tokens
    assert "belt" in tokens
    assert "car" in tokens


def test_title_tokens_punctuation_stripped():
    tokens = title_tokens("Timing belt (failure)!")
    assert "timing" in tokens
    assert "belt" in tokens
    assert "failure" in tokens


def test_title_similar_identical():
    assert title_similar("Timing belt failure", "Timing belt failure") is True


def test_title_similar_different():
    assert title_similar("Timing belt failure", "Water pump leak") is False


def test_title_similar_threshold():
    # "Timing belt failure" vs "Timing belt replacement" → shares "timing" + "belt" out of 4 unique tokens
    assert title_similar("Timing belt failure", "Timing belt replacement") is True


def test_title_similar_same_domain():
    assert title_similar("Water pump cracking", "Water pump housing leak") is True


def test_title_similar_empty():
    assert title_similar("", "Timing belt") is False
    assert title_similar("Timing belt", "") is False
    assert title_similar("", "") is False


# ── _best_in_cluster tests ───────────────────────────────────────────────────

def test_best_in_cluster_single():
    cr = _make_claim("id1", "Timing belt failure", severity="high")
    result = _best_in_cluster([cr])
    assert result.claim.id == "id1"
    assert result.strength == "confirmed"


def test_best_in_cluster_strength_preserved():
    """When merging, the strongest strength (confirmed > due > reported) wins."""
    confirmed = _make_claim("id1", "Timing belt failure", strength="confirmed", severity="high")
    reported = _make_claim("id2", "Timing belt issue", strength="reported", severity="medium")
    result = _best_in_cluster([reported, confirmed])
    assert result.strength == "confirmed"


def test_best_in_cluster_severity_preserved():
    """Highest severity wins."""
    high = _make_claim("id1", "Timing belt failure", severity="high")
    low = _make_claim("id2", "Timing belt issue", severity="low")
    result = _best_in_cluster([low, high])
    assert result.claim.severity == "high"


def test_best_in_cluster_title_from_best():
    """Title should come from the highest-severity member."""
    high = _make_claim("id1", "Timing belt catastrophic failure", severity="high")
    low = _make_claim("id2", "Timing belt minor noise", severity="low")
    result = _best_in_cluster([low, high])
    assert "catastrophic" in result.claim.title


def test_best_in_cluster_confidence_merged():
    c1 = _make_claim("id1", "Timing belt failure", confidence=0.6)
    c2 = _make_claim("id2", "Timing belt issue", confidence=0.9)
    result = _best_in_cluster([c1, c2])
    assert result.claim.confidence == 0.9


def test_best_in_cluster_rationale_merged():
    c1 = _make_claim("id1", "Timing belt failure",
                     rationale="The belt can snap at high mileage.")
    c2 = _make_claim("id2", "Timing belt issue",
                     rationale="Replace preventively at 90k km.")
    result = _best_in_cluster([c1, c2])
    assert "belt can snap" in result.claim.rationale
    assert "Replace preventively" in result.claim.rationale


def test_best_in_cluster_rationale_dedup():
    """Near-duplicate rationale should be merged (not duplicated)."""
    c1 = _make_claim("id1", "Timing belt failure",
                     rationale="The belt can snap at high mileage. Replace at 90k.")
    c2 = _make_claim("id2", "Timing belt failure",
                     rationale="The belt can snap at high mileage. Replace at 90k.")
    result = _best_in_cluster([c1, c2])
    # Should not contain the same text twice
    assert result.claim.rationale.count("Replace at 90k") == 1


# ── _deduplicate_results tests ───────────────────────────────────────────────

def test_dedup_empty_list():
    assert _deduplicate_results([]) == []


def test_dedup_single_item():
    cr = _make_claim("id1", "Timing belt failure")
    result = _deduplicate_results([cr])
    assert len(result) == 1
    assert result[0].claim.id == "id1"


def test_dedup_no_merge_needed():
    """Different domain, different titles → no merge."""
    c1 = _make_claim("id1", "Timing belt failure", domain="engine")
    c2 = _make_claim("id2", "Water pump leak", domain="engine")
    result = _deduplicate_results([c1, c2])
    assert len(result) == 2


def test_dedup_similar_titles_same_domain():
    """Same domain, similar titles → merged to one."""
    c1 = _make_claim("id1", "Timing belt failure", domain="engine")
    c2 = _make_claim("id2", "Timing belt replacement interval", domain="engine")
    result = _deduplicate_results([c1, c2])
    assert len(result) == 1


def test_dedup_same_title_different_domain():
    """Same title but different domains → NOT merged."""
    c1 = _make_claim("id1", "Timing belt failure", domain="engine")
    c2 = _make_claim("id2", "Timing belt failure", domain="transmission")
    result = _deduplicate_results([c1, c2])
    assert len(result) == 2


def test_dedup_three_similar_one_different():
    """3 engine timing belt claims → merged to 1, plus 1 separate transmission claim."""
    c1 = _make_claim("id1", "Timing belt failure", domain="engine")
    c2 = _make_claim("id2", "Timing belt replacement interval", domain="engine")
    c3 = _make_claim("id3", "Timing belt wear symptoms", domain="engine")
    c4 = _make_claim("id4", "DSG mechatronics failure", domain="transmission")
    result = _deduplicate_results([c1, c2, c3, c4])
    assert len(result) == 2


def test_dedup_multiple_domains():
    """Each domain operates independently."""
    c1 = _make_claim("id1", "Timing belt failure", domain="engine")
    c2 = _make_claim("id2", "Timing belt replacement", domain="engine")  # merged with c1
    c3 = _make_claim("id3", "DSG mechatronics failure", domain="transmission")
    c4 = _make_claim("id4", "DQ200 valve body cracking", domain="transmission")
    c5 = _make_claim("id5", "DSG clutch wear", domain="transmission")    # might merge with c3 or c4
    result = _deduplicate_results([c1, c2, c3, c4, c5])
    # Engine: 1 group (c1+c2 merge via "timing belt"). Transmission: 3 separate
    # (none of the transmission titles reach 0.4 Jaccard with each other)
    assert len(result) == 4


def test_dedup_different_titles_no_merge():
    """Completely different titles within same domain → not merged."""
    c1 = _make_claim("id1", "Timing belt failure", domain="engine")
    c2 = _make_claim("id2", "Water pump leak", domain="engine")
    c3 = _make_claim("id3", "Carbon build-up on valves", domain="engine")
    result = _deduplicate_results([c1, c2, c3])
    assert len(result) == 3


# ── Integration test with real resolve_claims ────────────────────────────────

def test_dedup_not_breaking_existing_tests(db, megane4_claims):
    """The dedup should not break existing claims — ensure resolve_claims still works."""
    from backend.core.matcher import MatchResult
    from backend.core.resolver import resolve_claims

    match = MatchResult(["megane4_k9k_90"], "exact", "")
    results = resolve_claims(match, db)
    # Should still return results (filtered by DB query, not dedup)
    assert len(results) >= 1
    titles = [r.claim.title for r in results]
    assert any("injector" in t.lower() for t in titles)


def test_dedup_strength_in_merged_results(db, megane4_variants):
    """When dedup merges claims, the strength must survive through to output."""
    from backend.core.matcher import MatchResult
    from backend.core.resolver import _servable_claims_for, _apply_context, _deduplicate_results

    claims = _servable_claims_for("megane4_k9k_90", db)
    results = _apply_context(claims, None)
    deduped = _deduplicate_results(results)

    # All results should have valid strength
    for r in deduped:
        assert r.strength in ("confirmed", "reported", "due", "due_stated"), f"Invalid strength: {r.strength}"
