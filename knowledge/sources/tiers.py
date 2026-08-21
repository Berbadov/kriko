"""Source tier resolution — Phase 1 of the v3 overhaul.

Turns `knowledge/catalog/source_tiers.yaml` into a callable: every source
domain maps to a tier with a trust weight. The registry is the data, this
module is the single enforcement point (same pattern as domains.py: the
prompt can drift, this can't).

Used by verdicts/coverage for decomposed confidence
(source_trust x corroboration x specificity) and by the hub source browser.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

_REGISTRY = Path(__file__).resolve().parent.parent / "catalog" / "source_tiers.yaml"


@lru_cache(maxsize=1)
def _registry() -> dict:
    with open(_REGISTRY, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _registrable_domain(host: str) -> str:
    """Reduce a host to its last two labels (co.uk-style TLDs excepted).

    'www.example.co.uk' -> 'example.co.uk'; 'en.mercedesassistance.com' ->
    'mercedesassistance.com'. Deliberately crude: registry lookups want the
    site identity, and explicit subdomain entries in the registry (like
    'en.mercedesassistance.com') are checked verbatim first.
    """
    host = host.lower().strip(".")
    if not host:
        return ""
    multi_tld = host.endswith((".co.uk", ".com.tr", ".com.au", ".co.za", ".com.cn"))
    parts = host.split(".")
    keep = 3 if (multi_tld and len(parts) > 2) else 2
    return ".".join(parts[-keep:]) if len(parts) > keep else host


def domain_from_url(url: str | None) -> str:
    """Extract the registrable domain from a source URL. '' when unparseable."""
    if not url:
        return ""
    host = url.strip().lower()
    if "://" in host:
        host = host.split("://", 1)[1]
    host = host.split("/", 1)[0]
    if "@" in host:
        host = host.split("@", 1)[1]
    host = host.split(":", 1)[0]  # strip port
    return host


def resolve_tier(domain_or_url: str | None) -> tuple[str, float]:
    """Map a domain (or full URL) to (tier, trust).

    Lookup order: verbatim host -> verbatim registrable domain -> fallback
    rules -> default. Never raises; an unknown domain lands on the default
    tier (seo_blog), which is the conservative choice: unclassified sources
    must not inherit trust.
    """
    reg = _registry()
    tiers: dict[str, dict] = reg["tiers"]
    default: str = reg["default"]

    host = domain_from_url(domain_or_url) if domain_or_url and "://" in str(domain_or_url) \
        else (domain_or_url or "").strip().lower().split("/")[0]
    if not host:
        return default, tiers[default]["trust"]

    domains: dict[str, dict] = reg.get("domains", {})
    for cand in (host, _registrable_domain(host)):
        if cand in domains:
            tier = domains[cand]["tier"]
            return tier, tiers[tier]["trust"]

    registrable = _registrable_domain(host)
    for rule in reg.get("rules", []):
        for needle in rule.get("domain_contains", []):
            if needle.strip(".") in host or needle.strip(".") in registrable:
                tier = rule["tier"]
                return tier, tiers[tier]["trust"]

    return default, tiers[default]["trust"]


def trust_of(domain_or_url: str | None) -> float:
    """Convenience: just the trust weight."""
    return resolve_tier(domain_or_url)[1]


def all_tiers() -> dict[str, float]:
    """Tier name -> trust weight (for the hub source browser)."""
    return {name: t["trust"] for name, t in _registry()["tiers"].items()}
