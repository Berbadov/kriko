"""The TCMB bulletin, read the way the Estimate screen reads it.

The fixture is a cut-down copy of the public bulletin's shape: one currency
quoted per unit, one quoted per hundred. The test pins the direction (TRY per
one unit), the date, and the refusal to turn a blank quote into zero.
"""

from app.fx import parse_tcmb

BULLETIN = """<?xml version="1.0" encoding="UTF-8"?>
<Tarih_Date Tarih="19.11.2026" Date="11/19/2026" Bulten_No="2026/218">
  <Currency CrossOrder="0" Kod="USD" CurrencyCode="USD">
    <Unit>1</Unit><ForexBuying>50.3786</ForexBuying><ForexSelling>50.4694</ForexSelling>
  </Currency>
  <Currency CrossOrder="1" Kod="EUR" CurrencyCode="EUR">
    <Unit>1</Unit><ForexBuying>58.10</ForexBuying><ForexSelling>58.20</ForexSelling>
  </Currency>
  <Currency CrossOrder="2" Kod="JPY" CurrencyCode="JPY">
    <Unit>100</Unit><ForexBuying>32.10</ForexBuying><ForexSelling>32.20</ForexSelling>
  </Currency>
  <Currency CrossOrder="3" Kod="XDR" CurrencyCode="XDR">
    <Unit>1</Unit><ForexBuying/><ForexSelling/>
  </Currency>
</Tarih_Date>
"""


def test_rates_are_try_per_one_unit_and_the_date_is_the_bulletins():
    got = parse_tcmb(BULLETIN)
    assert got["base"] == "TRY"
    assert got["date"] == "2026-11-19"
    assert got["bulletin"] == "2026/218"
    assert got["rates"]["TRY"] == 1.0
    assert got["rates"]["USD"] == 50.4694
    assert got["rates"]["EUR"] == 58.2


def test_a_currency_quoted_per_hundred_is_divided_by_its_unit():
    assert parse_tcmb(BULLETIN)["rates"]["JPY"] == 0.322


def test_a_blank_quote_is_absent_rather_than_zero():
    assert "XDR" not in parse_tcmb(BULLETIN)["rates"]
