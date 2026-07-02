"""Phase 3 — gate_inspection_value offline tests.

Two stoplist cases run fully offline (no API key, no network).
Two high-value "keep" cases mock _ask so they also run offline.
"""

from knowledge.judge import gate_inspection_value


# ── Stoplist rejects (zero cost — no API key required) ────────────────────────

def test_stoplist_brake_fluid():
    """'brake fluid' is in INSPECTION_COVERED → rejected without LLM."""
    result = gate_inspection_value(
        "Check brake fluid level",
        "Brake fluid absorbs moisture over time and should be checked regularly.",
    )
    assert result.passed is False
    assert "stoplist" in result.reason.lower()


def test_stoplist_esp_light():
    """'ESP warning light' matches WARNING_LIGHT_PATTERNS → rejected without LLM."""
    result = gate_inspection_value(
        "ESP warning light fault",
        "The ESP warning light illuminates when the stability control system detects a fault.",
    )
    assert result.passed is False
    assert "warning light" in result.reason.lower()


# ── High-value claims (stoplist misses → LLM path, _ask mocked) ──────────────

def test_high_value_edc_kept(monkeypatch):
    """EDC mechatronics claim is config-specific and mileage-gated → kept."""
    monkeypatch.setattr("knowledge.judge.MISTRAL_API_KEY", "test-key")
    monkeypatch.setattr("knowledge.judge._ask", lambda *a, **kw: (False, "specific failure mode"))

    result = gate_inspection_value(
        "EDC dual-clutch mechatronics wear at 120k km",
        "The EDC (Efficient Dual Clutch) mechatronics unit and clutch pack are known "
        "to wear above 120,000 km on H5F/H5H variants. Not covered by standard inspection.",
    )
    assert result.passed is True


def test_high_value_timing_belt_kept(monkeypatch):
    """Timing belt interval claim is mileage-predictable and high-consequence → kept."""
    monkeypatch.setattr("knowledge.judge.MISTRAL_API_KEY", "test-key")
    monkeypatch.setattr("knowledge.judge._ask", lambda *a, **kw: (False, "maintenance interval specific to this engine"))

    result = gate_inspection_value(
        "1.5 dCi (K9K) timing belt due at 90,000 km or 5 years",
        "The K9K uses a rubber timing belt with a Renault-specified interval. "
        "A snapped belt causes catastrophic valve/piston contact. "
        "Not caught by a standard pre-purchase inspection.",
    )
    assert result.passed is True


# ── Ambiguous inspection terms — "oil consumption" et al. cut both ways ──────
#
# Regression coverage: a blanket keyword reject killed well-documented,
# engine-specific chronic defects (VW EA111/EA211 1.4 TSI piston-ring oil
# consumption) alongside truly generic dipstick-check mentions. Both branches
# below resolve deterministically, without an LLM call (no API key needed).

def test_engine_specific_oil_consumption_kept_without_llm():
    """An engine code + mileage figure alongside 'oil consumption' → kept, no LLM call."""
    result = gate_inspection_value(
        "Piston ring wear leading to high oil consumption",
        "First-generation EA211 1.4 TFSI engines suffer from premature piston ring "
        "wear, causing excessive oil consumption (up to 0.5L per 1,000 km) between "
        "60,000-120,000 km. If neglected, this can lead to severe engine damage.",
    )
    assert result.passed is True
    assert "specificity" in result.reason.lower()


def test_generic_oil_consumption_rejected_without_llm():
    """No engine/mileage signal alongside 'oil consumption' → rejected, no LLM call."""
    result = gate_inspection_value(
        "Generic oil consumption check",
        "The car may be consuming oil, check the dipstick before buying any used car.",
    )
    assert result.passed is False
    assert "generic" in result.reason.lower()
