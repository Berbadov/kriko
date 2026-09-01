"""Canonical claim-domain vocabulary — single source of truth.

`domain` is a freeform string in CandidateClaim/claim YAML with no enum
enforcement anywhere in the pipeline, so the extraction LLM has drifted into
inventing values ("cooling system", "HVAC", "mechanical", "steering",
"safety") and multi-value joins ("engine|brakes|suspension",
"turbocharger/fuel system") — confirmed across ea888/h5d_100/megane4_body/
dc4/clio5_body and others in packs/cars/data/parts/**/*.yaml.

This is not cosmetic: backend/core/resolver.py's `_claims_share_domain()`
does an exact string match to group maintenance claims by domain — a
malformed value like "engine|brakes|suspension" never matches any
single-value "engine" claim, silently breaking that grouping.

`normalize_domain()` coerces any raw value to one of VALID_DOMAINS. It never
raises and never drops a claim — an unmappable value falls back to
"general" rather than being rejected, since a dropped claim is a completeness
regression, not a quality improvement.
"""

import re

# Canonical vocabulary. Extraction should only ever emit these (see
# extract.py's SYSTEM_PROMPT), but this module is the enforcement point,
# not the prompt — the prompt can drift, this can't.
VALID_DOMAINS: frozenset[str] = frozenset({
    "engine", "transmission", "electrical", "emissions", "fuel system",
    "brakes", "suspension", "cooling", "body", "general",
})

# Observed invented/near-synonym values -> nearest canonical bucket.
# Only add an alias here for a value actually seen in the wild — this table
# documents real drift, not speculative synonyms.
_DOMAIN_ALIASES: dict[str, str] = {
    "cooling system": "cooling",
    "turbocharger": "engine",
    "hvac": "general",
    "mechanical": "general",
    "steering": "suspension",
    "safety": "general",
}

_SPLIT_RE = re.compile(r"[|/]")


def normalize_domain(raw: str | None) -> str:
    """Coerce a raw domain string to one of VALID_DOMAINS.

    Multi-value strings ("engine|brakes|suspension", "turbocharger/fuel
    system") are split on the separator and only the first value is kept —
    domain is a single-select field downstream (resolver grouping, display),
    not a tag list. Falls back to "general" when the value is empty or
    doesn't map to anything canonical, rather than raising.
    """
    if not raw:
        return "general"
    first = _SPLIT_RE.split(raw.strip(), maxsplit=1)[0].strip().lower()
    first = _DOMAIN_ALIASES.get(first, first)
    return first if first in VALID_DOMAINS else "general"
