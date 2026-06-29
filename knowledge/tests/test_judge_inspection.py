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
