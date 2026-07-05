"""Turkish-language → internal canonical value maps for matcher input."""

import logging
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import yaml

log = logging.getLogger(__name__)

_FUEL_MAP: dict[str, str] = {
    "benzin": "petrol",
    "benzinli": "petrol",       # Sahibinden's adjective form ("petrol-fueled")
    "petrol": "petrol",
    "gasolina": "petrol",
    "dizel": "diesel",
    "diesel": "diesel",
    "motorin": "diesel",
    "lpg": "lpg",
    "lpg & benzin": "petrol",   # LPG-converted petrol — match as petrol variant
    "lpg/benzin": "petrol",
    "benzin & lpg": "petrol",
    "lpg & benzinli": "petrol",
    "benzinli & lpg": "petrol",
    "hibrit": "hybrid",
    "hybrid": "hybrid",
    "elektrik": "electric",
    "electric": "electric",
    "elektrikli": "electric",
}

_TX_MAP: dict[str, str] = {
    "manuel": "manual",
    "manual": "manual",
    "otomatik": "automatic",
    "automatic": "automatic",
    "yarı otomatik": "automatic",
    "yari otomatik": "automatic",
    "cvt": "automatic",
    "edc": "automatic",           # Renault dual-clutch auto
    "dct": "automatic",
    "dsg": "automatic",
    "tiptronic": "automatic",
    "s-tronic": "automatic",
    "powershift": "automatic",
    "steptronic": "automatic",
    "multimode": "automatic",
    "eld": "automatic",           # Renault ELD (single-clutch auto)
}

# Genuine spelling/abbreviation aliases for makes — NOT fixable by _slugify()
# alone (an abbreviation or compound name, not an accent/punctuation variant).
# Kept as a small hardcoded exception per CLAUDE.md's scalability principle:
# this is a closed vocabulary of alternate spellings for the SAME brand, not a
# per-car-model registry that has to grow with catalog coverage.
_MAKE_ALIASES: dict[str, str] = {
    "vw": "volkswagen",
    "mercedes-benz": "mercedes",
}

_VARIANTS_DIR = Path(__file__).parent.parent / "data" / "variants"


def _slugify(val: str) -> str:
    """Lowercase, strip accents, drop all non-alphanumeric characters.

    "Mégane" -> "megane", "Citroën" -> "citroen", "C-HR" -> "chr" — this is
    what lets normalize_make/normalize_model recognize any make/model without
    a per-car hardcoded map entry (see CLAUDE.md's scalability principle).
    """
    nfkd = unicodedata.normalize("NFKD", val)
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", ascii_only.lower())


@lru_cache(maxsize=1)
def _catalog_makes_models() -> tuple[frozenset[str], frozenset[str]]:
    """Distinct (make, model) slugs already onboarded, read straight off the
    variants catalog — not hand-maintained, so it grows automatically as new
    models are onboarded (same pattern as knowledge/stoplists.py's
    catalog_code_manufacturers()).

    Used only for a soft "not yet onboarded" log signal, never to reject a
    normalization result — a make/model outside this set still normalizes via
    _slugify() and simply won't match anything in matcher.py's DB query
    (fail-open, not fail-closed; see docs/design_flaws.md's praise of
    resolver.py for the same distinction).
    """
    makes: set[str] = set()
    models: set[str] = set()
    for path in _VARIANTS_DIR.glob("*.yaml"):
        try:
            rows = yaml.safe_load(path.read_text()) or []
        except yaml.YAMLError:
            continue
        for row in rows:
            if row.get("make"):
                makes.add(str(row["make"]).lower())
            if row.get("model"):
                models.add(str(row["model"]).lower())
    return frozenset(makes), frozenset(models)


def _norm(val: str | None, mapping: dict[str, str]) -> str | None:
    if not val:
        return None
    key = val.strip().lower()
    return mapping.get(key)


def _normalize_car_field(raw: str | None, known: frozenset[str], field: str) -> str | None:
    if not raw:
        return None
    key = raw.strip().lower()
    if field == "make":
        key = _MAKE_ALIASES.get(key, key)
    slug = _slugify(key)
    if slug not in known:
        log.info(
            "normalize_%s: %r -> %r not yet in the onboarded catalog — "
            "matching will fail-open to no_match rather than a false positive",
            field, raw, slug,
        )
    return slug


def normalize_fuel(raw: str | None) -> str | None:
    return _norm(raw, _FUEL_MAP)


def normalize_transmission(raw: str | None) -> str | None:
    if not raw:
        return None
    key = raw.strip().lower()
    # Try exact match first
    if key in _TX_MAP:
        return _TX_MAP[key]
    # Try substring match for compound strings like "Manuel / Ön"
    for token, value in _TX_MAP.items():
        if token in key:
            return value
    return None


def normalize_make(raw: str | None) -> str | None:
    makes, _ = _catalog_makes_models()
    return _normalize_car_field(raw, makes, "make")


def normalize_model(raw: str | None) -> str | None:
    _, models = _catalog_makes_models()
    return _normalize_car_field(raw, models, "model")
