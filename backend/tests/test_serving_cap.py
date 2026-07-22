"""_cap_risks() — the per-listing "few" guarantee (overhaul Phase B).

After ranking, cap the served risks to a small N so a buyer sees the few that
matter, not 100. Evidence-backed items (confirmed / due / due_stated) are never
dropped by the cap — only the "reported" tail is trimmed. Input is assumed
already ranked (best first); output preserves that order.
"""

from backend.api.main import _cap_risks, MAX_RISKS_PER_LISTING
from backend.api.schemas import RiskItem


def _risk(title, strength="reported", consequence="medium"):
    return RiskItem(
        title=title, severity="medium", consequence=consequence, domain="engine",
        rationale="r", inspection_advice="a", source_count=0, strength=strength,
    )


def test_under_cap_is_unchanged():
    risks = [_risk(f"r{i}") for i in range(3)]
    assert _cap_risks(risks, 8) == risks


def test_over_cap_truncates_to_n_keeping_top():
    risks = [_risk(f"r{i}") for i in range(12)]
    out = _cap_risks(risks, 8)
    assert len(out) == 8
    assert [r.title for r in out] == [f"r{i}" for i in range(8)]  # top 8, order kept


def test_evidence_backed_items_are_never_capped():
    # 10 confirmed items, cap of 8 → all 10 survive (never hide a confirmed risk).
    risks = [_risk(f"c{i}", strength="confirmed") for i in range(10)]
    out = _cap_risks(risks, 8)
    assert len(out) == 10


def test_protected_kept_and_slots_filled_with_reported():
    risks = (
        [_risk(f"c{i}", strength="confirmed") for i in range(3)]
        + [_risk(f"r{i}") for i in range(9)]
    )
    out = _cap_risks(risks, 8)
    assert len(out) == 8
    assert [r.title for r in out[:3]] == ["c0", "c1", "c2"]  # protected survive, order kept
    assert out[3].title == "r0"  # then the top reported fill the rest


def test_due_maintenance_is_protected():
    risks = [_risk(f"d{i}", strength="due") for i in range(10)]
    assert len(_cap_risks(risks, 8)) == 10


def test_default_cap_is_a_small_number():
    assert 1 <= MAX_RISKS_PER_LISTING <= 12
