"""Source-document relevance gate — a fetched page/transcript that's 100%
about a DIFFERENT manufacturer's part must never reach extraction, even
though the resulting claim TEXT can read as generic/plausible for the part
actually being researched.

Regression: k9k_100.yaml's curated sources included pages entirely about
VW's 1.5/1.6 TDI (myenginespecs.com/volkswagen/vw-1-5-tdi-..., a VW Polo TDI
ownership review, ...) under Renault's K9K part. mentions_foreign_manufacturer_code
(claim-text level) and mentions_sibling_code both miss this: the extracted
claim titles ("Connecting rod bearing failure", "Delphi injection pump
failure") never cite a foreign code themselves. Only the SOURCE PAGE gives it
away. See docs/design_flaws.md remediation, 2026-07-05.
"""

from unittest.mock import patch

from packs.cars.pipeline.sources.curated import CuratedSource
from packs.cars.pipeline.stoplists import catalog_code_manufacturers, document_is_foreign_to_part

VW_TDI_TEXT = (
    "The Volkswagen 1.5 TDI (EA211 evo) engine has been reported to suffer "
    "from timing belt issues in some markets. Owners of the VW Polo report "
    "similar symptoms after 100,000 km."
)


def setup_module():
    catalog_code_manufacturers.cache_clear()


def teardown_module():
    catalog_code_manufacturers.cache_clear()


# ── document_is_foreign_to_part (pure) ───────────────────────────────────────

def test_flags_wrong_manufacturer_page_for_part_centric_call():
    # process.run_part passes model=part_id ("k9k_100") for part-centric runs.
    assert document_is_foreign_to_part(VW_TDI_TEXT, "part", "k9k_100")


def test_flags_wrong_manufacturer_page_for_model_centric_call():
    # process.run passes the real make ("renault") for model-centric runs.
    assert document_is_foreign_to_part(VW_TDI_TEXT, "renault", "megane")


def test_allows_page_that_also_mentions_own_code():
    text = VW_TDI_TEXT + " By comparison, the Renault K9K has a different injection design."
    assert not document_is_foreign_to_part(text, "part", "k9k_100")


def test_allows_page_that_mentions_own_manufacturer_name():
    text = VW_TDI_TEXT + " Renault engines are covered separately below."
    assert not document_is_foreign_to_part(text, "part", "k9k_100")


def test_allows_genuine_own_part_content():
    text = "The K9K 1.5 dCi suffers from EGR cooler cracking and DPF clogging at high mileage."
    assert not document_is_foreign_to_part(text, "part", "k9k_100")


def test_allows_content_with_no_manufacturer_signal_at_all():
    assert not document_is_foreign_to_part("Rough idle and poor fuel economy reported.", "part", "k9k_100")


def test_fails_open_with_no_make_or_resolvable_model():
    assert not document_is_foreign_to_part(VW_TDI_TEXT, "", "unregistered_slug")


# ── Wired into CuratedSource._fetch_entry ────────────────────────────────────

@patch("packs.cars.pipeline.sources.curated._fetch_html", return_value="<html>irrelevant</html>")
@patch("trafilatura.extract", return_value=VW_TDI_TEXT)
def test_fetch_entry_skips_foreign_manufacturer_page(_extract, _html):
    entry = {"type": "page", "url": "https://example.com/vw-tdi-problems", "site_or_channel": "example.com"}
    doc = CuratedSource()._fetch_entry(entry, "part", "k9k_100")
    assert doc is None


@patch("packs.cars.pipeline.sources.curated._fetch_html", return_value="<html>irrelevant</html>")
@patch("trafilatura.extract", return_value="The K9K 1.5 dCi suffers from EGR cooler cracking.")
def test_fetch_entry_keeps_genuine_page(_extract, _html):
    entry = {"type": "page", "url": "https://example.com/k9k-egr", "site_or_channel": "example.com"}
    doc = CuratedSource()._fetch_entry(entry, "part", "k9k_100")
    assert doc is not None
    assert doc.url == "https://example.com/k9k-egr"
