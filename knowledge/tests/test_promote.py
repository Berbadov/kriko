"""write_promoted_claims — persistence + idempotency.

No LLM / no DB. Covers the postmortem fixes: review/held are persisted (not
discarded), and a re-run (e.g. --skip-extraction) does not clobber human edits,
re-add tombstoned junk, or create cross-run duplicates.
"""

import yaml

from knowledge.extract import CandidateClaim
from knowledge.promote import (
    Disposition,
    PromotionResult,
    write_promoted_claims,
)
from knowledge.sources.base import Document


def _claim(title, domain="engine", severity="medium"):
    return CandidateClaim(
        title=title,
        domain=domain,
        severity=severity,
        rationale=f"rationale for {title}",
        inspection_advice="check it",
        quote="some verbatim span",
    )


def _result(title, disposition, domain="engine"):
    doc = Document(text="src", url=f"https://x/{title}", site_or_channel="forum")
    return PromotionResult(
        claim=_claim(title, domain),
        disposition=disposition,
        score=0.5,
        confidence=0.6,
        promoted_by="auto" if disposition == Disposition.VERIFY else "pending_human",
        grounded_variant_ids=["megane4_k9k"],
        grounded_sources=[doc],
        reason="test",
    )


def _load(claims_dir, make="renault", model="megane4"):
    path = claims_dir / f"{make}_{model}.yaml"
    return yaml.safe_load(path.read_text()) if path.exists() else []


def test_persists_verified_review_held_not_rejected(tmp_path):
    results = [
        _result("K9K injector failure", Disposition.VERIFY),
        _result("EGR valve clogging issue", Disposition.REVIEW),
        _result("DPF regeneration trouble", Disposition.HELD),
        _result("Brakes wear over time", Disposition.REJECT),
    ]
    write_promoted_claims(results, "renault", "megane4", tmp_path)

    rows = _load(tmp_path)
    by_status = {r["status"] for r in rows}
    assert by_status == {"verified", "review", "held"}        # rejected dropped
    assert len(rows) == 3


def test_rerun_does_not_revert_human_promotion(tmp_path):
    # Run 1: a review claim is persisted.
    write_promoted_claims([_result("EGR valve clogging", Disposition.REVIEW)], "renault", "megane4", tmp_path)
    rows = _load(tmp_path)
    assert rows[0]["status"] == "review"

    # Human promotes it by editing one line.
    rows[0]["status"] = "verified"
    rows[0]["promoted_by"] = "human"
    (tmp_path / "renault_megane4.yaml").write_text(yaml.dump(rows, allow_unicode=True, sort_keys=False))

    # Run 2 (e.g. --skip-extraction) re-discovers the same claim.
    write_promoted_claims([_result("EGR valve clogging", Disposition.REVIEW)], "renault", "megane4", tmp_path)

    rows = _load(tmp_path)
    assert len(rows) == 1                       # not duplicated
    assert rows[0]["status"] == "verified"      # human edit preserved
    assert rows[0]["promoted_by"] == "human"


def test_tombstone_is_not_readded(tmp_path):
    write_promoted_claims([_result("Useless generic claim", Disposition.REVIEW)], "renault", "megane4", tmp_path)
    rows = _load(tmp_path)

    # Human buries junk by setting status: rejected (rather than deleting the line).
    rows[0]["status"] = "rejected"
    (tmp_path / "renault_megane4.yaml").write_text(yaml.dump(rows, allow_unicode=True, sort_keys=False))

    write_promoted_claims([_result("Useless generic claim", Disposition.REVIEW)], "renault", "megane4", tmp_path)

    rows = _load(tmp_path)
    assert len(rows) == 1
    assert rows[0]["status"] == "rejected"      # stays buried


def test_cross_run_near_duplicate_skipped(tmp_path):
    write_promoted_claims([_result("K9K injector failure", Disposition.VERIFY)], "renault", "megane4", tmp_path)

    # Re-phrased same issue, different claim_key (title[:20] differs) but same domain.
    write_promoted_claims([_result("K9K injector failure water ingress", Disposition.REVIEW)], "renault", "megane4", tmp_path)

    rows = _load(tmp_path)
    assert len(rows) == 1                        # title-Jaccard guard caught it


def test_same_run_duplicates_collapse(tmp_path):
    results = [
        _result("Timing chain stretch on K9K", Disposition.VERIFY),
        _result("K9K timing chain stretch wear", Disposition.REVIEW),
    ]
    write_promoted_claims(results, "renault", "megane4", tmp_path)

    rows = _load(tmp_path)
    assert len(rows) == 1


def test_different_domain_not_deduped(tmp_path):
    # Same words, different domain → genuinely distinct claims, both kept.
    results = [
        _result("Sensor failure", Disposition.VERIFY, domain="engine"),
        _result("Sensor failure", Disposition.VERIFY, domain="electrical"),
    ]
    write_promoted_claims(results, "renault", "megane4", tmp_path)

    rows = _load(tmp_path)
    assert len(rows) == 2


def test_cross_run_held_promoted_when_new_result_better(tmp_path):
    """Cross-run corroboration: a held claim is updated if new result is review/verified."""
    # Run 1: claim is held (gate_support failed → no sources)
    write_promoted_claims([_result("EDC clutch pack wear", Disposition.HELD)], "renault", "megane4", tmp_path)
    rows = _load(tmp_path)
    assert rows[0]["status"] == "held"

    # Run 2: improved gate_support finds a source → now review
    write_promoted_claims([_result("EDC clutch pack wear", Disposition.REVIEW)], "renault", "megane4", tmp_path)
    rows = _load(tmp_path)
    assert len(rows) == 1                    # not duplicated
    assert rows[0]["status"] == "review"    # promoted in-place


def test_cross_run_rejected_not_promoted(tmp_path):
    """A rejected (tombstoned) claim is never re-activated by cross-run logic."""
    write_promoted_claims([_result("Audio glitch", Disposition.REVIEW)], "renault", "megane4", tmp_path)
    rows = _load(tmp_path)
    rows[0]["status"] = "rejected"
    (tmp_path / "renault_megane4.yaml").write_text(yaml.dump(rows, allow_unicode=True, sort_keys=False))

    write_promoted_claims([_result("Audio glitch", Disposition.VERIFY)], "renault", "megane4", tmp_path)
    rows = _load(tmp_path)
    assert rows[0]["status"] == "rejected"  # tombstone holds


def test_cross_run_same_status_accumulates_sources(tmp_path):
    """A review claim with no sources gets sources added on re-run even if status stays review."""
    # Run 1: claim gets review but gate_support found no sources → sources=[]
    result_no_src = PromotionResult(
        claim=_claim("EDC clutch pack"),
        disposition=Disposition.REVIEW,
        score=0.0,
        confidence=0.0,
        promoted_by="pending_human",
        grounded_variant_ids=[],
        grounded_sources=[],
        reason="no sources",
    )
    write_promoted_claims([result_no_src], "renault", "megane4", tmp_path)
    rows = _load(tmp_path)
    assert rows[0]["status"] == "review"
    assert rows[0].get("sources", []) == []

    # Run 2: same claim at review, but now with a source
    write_promoted_claims([_result("EDC clutch pack", Disposition.REVIEW)], "renault", "megane4", tmp_path)
    rows = _load(tmp_path)
    assert len(rows) == 1             # not duplicated
    assert rows[0]["status"] == "review"  # status unchanged
    assert len(rows[0].get("sources", [])) == 1  # source accumulated!
