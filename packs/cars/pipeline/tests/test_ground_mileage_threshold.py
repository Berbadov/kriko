"""ground_mileage_threshold() — deterministic mileage-onset extractor.

Reads a claim's text and returns a conservative `min_mileage_km` gate ONLY when
the text states a mileage at which the failure/wear onsets (a km figure near an
onset/wear cue). Returns None otherwise → no gate → claim shows on every car
(fail-open). Same discipline as ground_year_window: emit only when grounded, and
bias LOW (take the earliest mileage in a range) so we never gate a claim off a
car that should still see it.
"""

from packs.cars.pipeline.ground_mileage_threshold import ground_mileage_threshold as g


def test_extracts_km_figure_with_onset_cue():
    assert g("Premature clutch wear by 80,000 km") == 80000


def test_dotted_thousands_separator():
    assert g("DSG mechatronic fluid degrades around 60.000 km") == 60000


def test_k_suffix_with_cue():
    assert g("Clutch pack wear typically appears around 80k") == 80000


def test_range_takes_lower_bound():
    # "60-80k" — the risk begins at the lower figure; gate on the earliest.
    assert g("Mechanical component failure at 60-80k km") == 60000


def test_turkish_bin_km_with_cue():
    assert g("60 bin km sonra şanzıman arızası görülüyor") == 60000


def test_speed_kmh_is_not_a_mileage():
    # "20 km/h" is a speed, not an odometer reading — must not become a gate.
    assert g("Hesitation and jerky take-off below 20 km/h") is None


def test_multiple_figures_take_minimum():
    assert g("Wear begins at 120,000 km and is severe by 180,000 km") == 120000


def test_km_figure_without_onset_cue_is_ignored():
    # Mileage present but as an incidental mention, not a failure onset.
    assert g("A 2019 example with 150,000 km was inspected for this report") is None


def test_implausible_figure_rejected():
    # Above the plausible odometer-onset ceiling — not a usable gate.
    assert g("The engine runs fine even beyond 500,000 km") is None


def test_no_mileage_returns_none():
    assert g("EGR cooler cracks cause coolant loss into the intake") is None


def test_empty_or_none_text_returns_none():
    assert g("") is None
    assert g(None) is None
