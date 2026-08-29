"""consequence_tier() — deterministic priority signal for ranking.

Maps a claim's text to high|medium|low by the failure SYSTEM it names, so the
serving sort can push expensive mechanical/electronic failures above comfort and
cosmetic ones ACROSS a whole car. Asymmetric like the other guards: an expensive
subsystem always wins (never demoted by a co-occurring comfort word), and a claim
is demoted to LOW only on an unambiguous comfort/cosmetic/performance term —
never on ambiguous words like "software" (infotainment vs ECU). Multilingual
(TR + EN) so Turkish terms like `mekatronik`/`enjektör` are not missed → buried.
"""

from packs.cars.pipeline.claims.consequence_tier import consequence_tier as t


def test_timing_belt_is_high():
    assert t("Timing belt failure", "cam belt snaps causing valve damage") == "high"


def test_turkish_mechatronic_is_high():
    # The recall-gap bug: `mekatronik` must match, not fall through to medium.
    assert t("Mekatronik Kart Arızası", "şanzıman güvenli moda geçiyor") == "high"


def test_control_unit_software_is_high_not_demoted():
    # "software" is ambiguous — on a TCM claim it is a high-consequence failure.
    assert t("TCM software lockups", "transmission control module adaptation fails") == "high"


def test_infotainment_freeze_is_low():
    assert t("MIB3 infotainment freezes", "head unit becomes unresponsive") == "low"


def test_expensive_system_wins_over_comfort_word():
    # "noise" is a comfort word, but a turbo failure is high-consequence.
    assert t("Turbocharger failure", "turbo whine and power loss") == "high"


def test_ride_comfort_is_low():
    assert t("Excessive road noise", "ride comfort and wind noise on the highway") == "low"


def test_turkish_injector_is_high():
    assert t("Enjektör arızası", "yakıt enjektörü sızıntısı") == "high"


def test_cosmetic_is_low():
    assert t("Paint peeling", "cosmetic clear-coat and stone chips on the bonnet") == "low"


def test_unclassified_defaults_to_medium():
    # No system vocabulary at all → medium, never demoted (fail-safe default).
    assert t("Intermittent fault", "an unusual electrical condition was reported") == "medium"


def test_bare_software_is_not_low():
    # Ambiguity guard: "software" with no comfort term must not become low.
    assert t("Software glitch", "occasional software instability") == "medium"


def test_flywheel_is_high():
    # Dual-mass flywheel failure is expensive/high-consequence — must not bury.
    assert t("Flywheel Failure Impact on Power Delivery", "dual-mass flywheel wear") == "high"


def test_turkish_flywheel_volant_is_high():
    assert t("Volant arızası", "çift kütleli volant aşınması") == "high"


def test_empty_text_is_medium():
    assert t("", "") == "medium"
