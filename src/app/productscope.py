"""Bind catalog identity to the thing sold, rather than a host it mentions.

Schema property roles are fixed; identity keys and values come from installed
adapters and subjects. No product/category vocabulary belongs here.
"""

import re
import unicodedata

RELATIONS = ("isAccessoryOrSparePartFor", "isConsumableFor")
BRAND_LABELS = {"ld:brand", "ld:manufacturer"}


def _words(value) -> list[str]:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    return re.findall(r"[^\W_]+", "".join(c for c in text if not unicodedata.combining(c)))


def _contains(text: list[str], phrase: list[str]) -> bool:
    return bool(phrase) and any(text[i:i + len(phrase)] == phrase
                                for i in range(len(text) - len(phrase) + 1))


def brand_keys(adapters) -> set[str]:
    return {key for spec in adapters for key, rule in (spec.get("identity") or {}).items()
            if BRAND_LABELS.intersection(rule.get("labels") or [])}


def consistent(fields: dict, identity: dict, adapters) -> bool:
    """Explicit sold-brand evidence overrides a name containing another brand."""
    declared = [_words(fields[label]) for label in BRAND_LABELS if fields.get(label)]
    expected = [_words(identity[key]) for key in brand_keys(adapters) if identity.get(key)]
    return not declared or not expected or any(one == other for one in declared for other in expected)


def filter_hits(hits: list[dict], name: str, fields: dict, adapters) -> list[dict]:
    """A contained alias is a mention until it anchors the sold product's name.

    Permit a catalog-declared brand before a model-code alias. Other preceding
    nouns (a battery, case, kit, etc.) cannot be silently discarded. Explicit
    host relations also exclude a host even if its alias starts the title.
    """
    title = _words(name)
    related = [_words(value) for label, value in fields.items()
               if any(label == f"ld:{rel}" or label == f"ld:{rel}.name" for rel in RELATIONS)]
    kept = []
    for hit in hits:
        specs = [spec for spec in adapters if spec.get("pack_id") == hit["pack_id"]]
        if not consistent(fields, hit.get("identity") or {}, specs):
            continue
        brands = [_words(hit["identity"][key]) for key in brand_keys(specs)
                  if hit.get("identity", {}).get(key)]
        for phrase in hit.get("why") or []:
            words = _words(phrase)
            if any(_contains(host, words) for host in related):
                continue
            if title[:len(words)] == words or any(
                title[:len(brand) + len(words)] == brand + words for brand in brands
            ):
                kept.append(hit)
                break
    return kept
