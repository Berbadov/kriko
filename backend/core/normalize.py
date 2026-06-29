"""Turkish-language → internal canonical value maps for matcher input."""

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

_MAKE_MAP: dict[str, str] = {
    "renault": "renault",
    "volkswagen": "volkswagen",
    "vw": "volkswagen",
    "toyota": "toyota",
    "bmw": "bmw",
    "mercedes": "mercedes",
    "mercedes-benz": "mercedes",
    "audi": "audi",
    "opel": "opel",
    "ford": "ford",
    "fiat": "fiat",
    "hyundai": "hyundai",
    "kia": "kia",
    "peugeot": "peugeot",
    "citroen": "citroen",
    "citroën": "citroen",
    "nissan": "nissan",
    "honda": "honda",
    "mazda": "mazda",
    "skoda": "skoda",
    "seat": "seat",
    "volvo": "volvo",
    "dacia": "dacia",
    "suzuki": "suzuki",
    "mini": "mini",
}

_MODEL_MAP: dict[str, str] = {
    # Renault
    "megane": "megane",
    "mégane": "megane",
    "clio": "clio",
    "captur": "captur",
    "kadjar": "kadjar",
    "kangoo": "kangoo",
    "fluence": "fluence",
    "scenic": "scenic",
    "laguna": "laguna",
    "talisman": "talisman",
    "zoe": "zoe",
    "symbol": "symbol",
    "latitude": "latitude",
    # Volkswagen
    "golf": "golf",
    "polo": "polo",
    "passat": "passat",
    "tiguan": "tiguan",
    "touareg": "touareg",
    "jetta": "jetta",
    "caddy": "caddy",
    "transporter": "transporter",
    # Toyota
    "corolla": "corolla",
    "yaris": "yaris",
    "rav4": "rav4",
    "c-hr": "chr",
    "chr": "chr",
    "camry": "camry",
    "hilux": "hilux",
    # Dacia
    "duster": "duster",
    "sandero": "sandero",
    "logan": "logan",
    "spring": "spring",
    # Peugeot
    "208": "208",
    "308": "308",
    "2008": "2008",
    "3008": "3008",
    "508": "508",
    # others added as needed
}


def _norm(val: str | None, mapping: dict[str, str]) -> str | None:
    if not val:
        return None
    key = val.strip().lower()
    return mapping.get(key)


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
    return _norm(raw, _MAKE_MAP)


def normalize_model(raw: str | None) -> str | None:
    return _norm(raw, _MODEL_MAP)
