"""Recovering required listing fields from the URL and title.

Live failure: the extension's DOM scrape returns nothing for some listings
(Sahibinden redesigns the info-list markup), and the backend rejects the whole
listing with "Missing required fields: ['make', 'fuel']" — even though the
listing URL literally contains the make and the title contains the engine badge.

The scrape is one fragile source for every required field. The URL slug and the
title are independent, stable sources for the same facts. Recovery is a fallback
only: a field the scraper DID read is never overwritten.
"""

from backend.core.recover import recover_listing_fields


URL = ("https://www.sahibinden.com/ilan/vasita-otomobil-volkswagen-golf-"
       "1-6-tdi-bluemotion-comfortline-1234567890/detay")


# ── make / model, derived from the catalog (no hardcoded car list) ───────────

def test_make_and_model_recovered_from_url_slug():
    out = recover_listing_fields({"url": URL})
    assert out["make"] == "volkswagen"
    assert out["model"] == "golf"


def test_make_and_model_recovered_from_title():
    out = recover_listing_fields(
        {"title": "2014 Volkswagen Golf 1.6 TDI BlueMotion Comfortline"})
    assert out["make"] == "volkswagen"
    assert out["model"] == "golf"


def test_scraped_values_are_never_overwritten():
    out = recover_listing_fields({"url": URL, "make": "Renault", "model": "Clio"})
    assert out["make"] == "Renault"
    assert out["model"] == "Clio"


def test_make_not_in_catalog_is_not_invented():
    out = recover_listing_fields(
        {"url": "https://www.sahibinden.com/ilan/vasita-otomobil-lada-niva-1-7-99/detay"})
    assert out.get("make") is None


# ── fuel, from the engine badge (closed engineering vocabulary) ──────────────

def test_diesel_badge_in_title_recovers_fuel():
    out = recover_listing_fields({"title": "2014 Volkswagen Golf 1.6 TDI"})
    assert out["fuel_type"] == "dizel"


def test_petrol_badge_in_title_recovers_fuel():
    out = recover_listing_fields({"title": "2019 Renault Clio 1.3 TCe"})
    assert out["fuel_type"] == "benzin"


def test_diesel_badge_in_url_recovers_fuel():
    assert recover_listing_fields({"url": URL})["fuel_type"] == "dizel"


def test_explicit_fuel_word_recovers_fuel():
    out = recover_listing_fields({"title": "Volkswagen Golf Dizel Otomatik"})
    assert out["fuel_type"] == "dizel"


def test_scraped_fuel_is_never_overwritten():
    out = recover_listing_fields({"title": "Golf 1.6 TDI", "fuel_type": "Benzin"})
    assert out["fuel_type"] == "Benzin"


def test_no_badge_does_not_invent_a_fuel():
    out = recover_listing_fields({"title": "2014 Volkswagen Golf Comfortline"})
    assert out.get("fuel_type") is None


def test_conflicting_badges_do_not_guess():
    # A title naming both a petrol and a diesel badge is ambiguous — a wrong fuel
    # picks the wrong variant and serves the wrong engine's risks. Stay silent.
    out = recover_listing_fields({"title": "Golf 1.6 TDI vs 1.4 TSI karşılaştırma"})
    assert out.get("fuel_type") is None


# ── year ────────────────────────────────────────────────────────────────────

def test_year_recovered_from_title():
    assert recover_listing_fields({"title": "2014 Volkswagen Golf"})["year"] == 2014


def test_implausible_year_is_not_recovered():
    out = recover_listing_fields({"title": "Volkswagen Golf 190.000 km"})
    assert out.get("year") is None


def test_empty_meta_recovers_nothing():
    assert recover_listing_fields({}) == {}


# ── End-to-end: the live failure, through the real serve path ───────────────

def test_analyze_serves_a_listing_whose_dom_scrape_returned_nothing(db, megane4_claims):
    """The reported bug: scrape yields no info list, so make/fuel are absent.

    Previously this returned NOT_MATCHED / "Missing required fields". The URL and
    title alone must now be enough to identify the variant.
    """
    from backend.api.main import run_analysis

    meta = {
        "url": ("https://www.sahibinden.com/ilan/vasita-otomobil-renault-megane-"
                "1-5-dci-joy-987654321/detay"),
        "title": "2018 Renault Megane 1.5 dCi Joy",
        "mileage_km": 150000,
        # make, model, fuel_type, year: all missing — the scrape failed.
    }
    _ctx, match, _served, resp = run_analysis(meta, db)

    assert "Missing required fields" not in match.notes
    assert match.variant_ids, f"no variant matched: {match.notes}"
    assert resp.coverage_state.value != "not_matched"
