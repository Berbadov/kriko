"""Recover required listing fields from the URL and title when the DOM scrape misses them.

The extension reads make/model/fuel/year out of Sahibinden's info-list markup.
That markup gets redesigned, and when it does the scrape returns nothing and the
backend rejects the listing outright ("Missing required fields: ['make',
'fuel']") — even though the URL slug literally contains the make and model, and
the title carries the engine badge. One fragile source was gating every required
field.

The URL and title are independent, stable sources for the same facts. This is a
strict fallback: a field the scraper DID read is never overwritten, and nothing
is invented — an unrecognised make or an ambiguous fuel stays absent so the
matcher can fail honestly rather than serve another engine's risks.

No hardcoded car data (CLAUDE.md): make/model are matched against the catalog
itself (normalize._catalog_makes_models). The fuel badges below are a closed
engineering vocabulary — engine-family suffixes, not car coverage — so
onboarding a new model adds nothing here.
"""

from __future__ import annotations

import re
from datetime import date

from backend.core.normalize import _catalog_makes_models, _slugify

# Engine badges that determine fuel unambiguously. Closed vocabulary: these are
# manufacturer fuel-system suffixes (TDI = Turbocharged Direct Injection diesel),
# not a per-car list.
_DIESEL_BADGES = (
    "tdi", "tdci", "dci", "hdi", "bluehdi", "cdi", "crdi", "cdti", "jtd",
    "multijet", "d4d", "ddis", "bluetec", "skyactiv-d", "dizel", "diesel",
)
_PETROL_BADGES = (
    "tsi", "tfsi", "tce", "vti", "thp", "mpi", "fsi", "gdi", "sce", "ecoboost",
    "benzin", "petrol",
)

# A badge must stand alone as a token — "tce" must not fire inside a random word.
def _badge_re(badges: tuple[str, ...]) -> re.Pattern[str]:
    return re.compile(r"(?<![a-z0-9])(" + "|".join(badges) + r")(?![a-z0-9])", re.I)


_DIESEL_RE = _badge_re(_DIESEL_BADGES)
_PETROL_RE = _badge_re(_PETROL_BADGES)

# A plausible model year, as a standalone token (so "190.000" can never match).
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")

_MIN_YEAR = 1980


def _listing_text(meta: dict) -> str:
    """The listing's own identifying text: URL slug + title."""
    return " ".join(str(meta.get(k) or "") for k in ("url", "title"))


def _recover_fuel(text: str) -> str | None:
    """Fuel implied by the engine badge, or None if absent/ambiguous.

    Returns a Turkish token normalize_fuel already understands, so this feeds the
    existing normalization rather than duplicating it.
    """
    diesel = bool(_DIESEL_RE.search(text))
    petrol = bool(_PETROL_RE.search(text))
    if diesel and petrol:
        return None  # ambiguous — a wrong fuel serves the wrong engine's risks
    if diesel:
        return "dizel"
    if petrol:
        return "benzin"
    return None


def _recover_year(text: str) -> int | None:
    max_year = date.today().year + 1
    for match in _YEAR_RE.finditer(text):
        year = int(match.group(1))
        if _MIN_YEAR <= year <= max_year:
            return year
    return None


def _recover_catalog_field(text: str, known: frozenset[str]) -> str | None:
    """The longest catalog make/model whose slug appears in the listing text.

    Longest-first so "golf" never wins over a longer model name that contains it.
    Matched on slugified text, so "Volkswagen", "volkswagen" and the URL's
    "-volkswagen-" all hit the same entry.
    """
    slug_text = _slugify(text)
    hits = [name for name in known if name and _slugify(name) in slug_text]
    return max(hits, key=len) if hits else None


def recover_listing_fields(meta: dict) -> dict:
    """Return `meta` with missing make/model/fuel_type/year filled from URL+title.

    Never overwrites a value the scraper already produced, and never invents one.
    """
    text = _listing_text(meta)
    if not text.strip():
        return dict(meta)

    out = dict(meta)
    makes, models = _catalog_makes_models()

    if not out.get("make"):
        if (make := _recover_catalog_field(text, makes)):
            out["make"] = make
    if not out.get("model"):
        if (model := _recover_catalog_field(text, models)):
            out["model"] = model
    if not out.get("fuel_type"):
        if (fuel := _recover_fuel(text)):
            out["fuel_type"] = fuel
    if not out.get("year"):
        if (year := _recover_year(text)):
            out["year"] = year

    return out
