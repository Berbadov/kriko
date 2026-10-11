"""Category-neutral, evidence-grounded product identity for local research."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Callable


IDENTITY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "canonical_name",
        "aliases",
        "variant",
        "identifiers",
        "unknowns",
        "evidence",
    ],
    "properties": {
        "canonical_name": {"type": "string"},
        "aliases": {"type": "array", "items": {"type": "string"}},
        "variant": {"type": "string"},
        "identifiers": {"type": "array", "items": {"type": "string"}},
        "unknowns": {"type": "array", "items": {"type": "string"}},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["claim", "quote"],
                "properties": {
                    "claim": {"type": "string"},
                    "quote": {"type": "string"},
                },
            },
        },
    },
}

# Only structural English words are ignored; identity data remains supplied per product.
_NON_IDENTITY_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
        "product",
        "model",
        "version",
    }
)
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True)
class ProductIdentity:
    """A cautious identity result; unresolved details remain explicitly unknown."""

    canonical_name: str
    aliases: tuple[str, ...] = ()
    variant: str = ""
    identifiers: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ("exact variant",)
    evidence: tuple[dict[str, str], ...] = ()
    resolved: bool = False
    source: str = "product prompt"

    def as_dict(self) -> dict[str, Any]:
        return {
            "canonical_name": self.canonical_name,
            "aliases": list(self.aliases),
            "variant": self.variant,
            "identifiers": list(self.identifiers),
            "unknowns": list(self.unknowns),
            "evidence": list(self.evidence),
            "resolved": self.resolved,
            "source": self.source,
        }


def identity_prompt(product_prompt: str, listing_text: str = "") -> str:
    """Ask a small model for identity supported only by the provided text."""
    return f"""Extract exact product identity from the reader prompt and listing. Never guess model,
trim, year, size, revision, configuration, or identifier. Leave unsupported details empty and
state them in unknowns. Aliases and variant must be explicit in supplied text. Evidence quotes
must be verbatim. Return only one JSON object matching this schema:
{json.dumps(IDENTITY_SCHEMA, ensure_ascii=False)}

READER PRODUCT PROMPT (untrusted):
{product_prompt}

LISTING TEXT (untrusted):
{listing_text}"""


def _json_object(raw: str) -> dict | None:
    if not isinstance(raw, str):
        return None
    try:
        value = json.loads(raw.strip())
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def _phrase_pattern(value: str) -> re.Pattern[str] | None:
    normalized = _normalize(value)
    if not normalized:
        return None
    phrase = r"\s+".join(re.escape(part) for part in normalized.split())
    return re.compile(r"(?<!\w)" + phrase + r"(?!\w)", re.UNICODE)


def _literal(value: object, corpus: str) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    pattern = _phrase_pattern(value)
    return bool(pattern and pattern.search(_normalize(corpus)))


def _distinctive_identifier(value: str) -> bool:
    return any(
        any(char.isalpha() for char in token) and any(char.isdigit() for char in token)
        for token in _TOKEN.findall(value)
    )


def _meaningful_tokens(value: str) -> set[str]:
    return {
        token
        for token in _TOKEN.findall(_normalize(value))
        if len(token) > 2 and token not in _NON_IDENTITY_WORDS
    }


def _identity_specific(value: str, product_prompt: str) -> bool:
    # A literal one-word request can name a product. Keep its variant unknown;
    # do not treat one token from a longer item name as the item being sold.
    if _normalize(value) == _normalize(product_prompt) and _meaningful_tokens(value):
        return True
    if _distinctive_identifier(product_prompt):
        value_ids = {
            token
            for token in _TOKEN.findall(_normalize(value))
            if _distinctive_identifier(token)
        }
        prompt_ids = {
            token
            for token in _TOKEN.findall(_normalize(product_prompt))
            if _distinctive_identifier(token)
        }
        if value_ids & prompt_ids:
            return True
        # A family name cannot replace the model code the reader supplied,
        # even when the extractor puts that code in a separate variant field.
        return False
    return len(_meaningful_tokens(value) & _meaningful_tokens(product_prompt)) >= 2


def _fallback(
    product_prompt: str, unknowns: tuple[str, ...] = ("exact variant",)
) -> ProductIdentity:
    """Preserve the reader's seed without claiming a resolved variant."""
    name = " ".join((product_prompt or "").split()) or "Unknown product"
    return ProductIdentity(canonical_name=name, unknowns=unknowns, resolved=False)


def parse_identity(
    raw: str, product_prompt: str, listing_text: str = ""
) -> ProductIdentity:
    """Parse strict JSON and keep only identity strings literally grounded in input."""
    data = _json_object(raw)
    if data is None:
        return _fallback(
            product_prompt, ("identity extraction failed", "exact variant")
        )
    required = set(IDENTITY_SCHEMA["required"])
    list_fields = ("aliases", "identifiers", "unknowns", "evidence")
    if set(data) != required or any(
        not isinstance(data.get(key), list) for key in list_fields
    ):
        return _fallback(
            product_prompt, ("identity response did not match schema", "exact variant")
        )

    prompt = product_prompt or ""
    corpus = f"{prompt}\n{listing_text or ''}"
    name, variant = data.get("canonical_name"), data.get("variant")
    if (
        not isinstance(name, str)
        or not _literal(name, corpus)
        or not _identity_specific(name, prompt)
        or not isinstance(variant, str)
    ):
        return _fallback(
            product_prompt,
            ("exact identity not verified from supplied text", "exact variant"),
        )

    variant = variant.strip() if _literal(variant, corpus) else ""
    aliases = tuple(
        dict.fromkeys(
            value.strip()
            for value in data["aliases"]
            if isinstance(value, str)
            and _literal(value, corpus)
            and _identity_specific(value, prompt)
            and _normalize(value) != _normalize(name)
        )
    )
    identifiers = tuple(
        dict.fromkeys(
            value.strip()
            for value in data["identifiers"]
            if isinstance(value, str)
            and _literal(value, corpus)
            and (_distinctive_identifier(value)
                 or (listing_text and _literal(name, listing_text)
                     and any(c.isalpha() for c in value)
                     and any(c.isdigit() for c in value)))
        )
    )
    evidence = tuple(
        {"claim": item["claim"].strip(), "quote": item["quote"].strip()}
        for item in data["evidence"]
        if isinstance(item, dict)
        and set(item) == {"claim", "quote"}
        and isinstance(item.get("claim"), str)
        and isinstance(item.get("quote"), str)
        and _literal(item["quote"], corpus)
    )
    unknowns = tuple(
        dict.fromkeys(
            value.strip()
            for value in data["unknowns"]
            if isinstance(value, str) and value.strip()
        )
    )
    if not variant and "exact variant" not in {_normalize(value) for value in unknowns}:
        unknowns += ("exact variant",)
    return ProductIdentity(
        canonical_name=name.strip(),
        aliases=aliases,
        variant=variant,
        identifiers=identifiers,
        unknowns=unknowns,
        evidence=evidence,
        resolved=bool(variant),
        source="listing text"
        if listing_text and (variant or identifiers)
        else "product prompt",
    )


def extract_identity(
    product_prompt: str,
    listing_text: str = "",
    llm: Callable[[str], str] | None = None,
) -> ProductIdentity:
    """Call a supplied extractor; parsing errors fall back, cancellation propagates."""
    if llm is None:
        return _fallback(product_prompt)
    return parse_identity(
        llm(identity_prompt(product_prompt, listing_text)), product_prompt, listing_text
    )


def identity_queries(identity: ProductIdentity, limit: int = 4) -> list[str]:
    """Build exact identity searches without adding a guessed model token."""
    names = list(
        dict.fromkeys(
            " ".join(name.split())
            for name in [identity.canonical_name, *identity.aliases]
            if name.strip()
        )
    )
    if not names:
        return []
    primary = names[0]
    queries = [f'"{primary}"']
    if identity.variant:
        queries.append(f'"{primary}" "{identity.variant}"')
    if identity.identifiers:
        queries.append(f'"{primary}" "{identity.identifiers[0]}"')
    queries.extend(f'"{alias}"' for alias in names[1:])
    return list(dict.fromkeys(queries))[: max(0, limit)]


def relevant_source(
    identity: ProductIdentity, title: str = "", snippet: str = ""
) -> bool:
    """Require exact identity; allow owner reports without repeating variant detail.

    Word-boundary matching permits whitespace variation and Unicode names. A
    source that only matches a category or generic descriptor does not qualify.
    """
    text = f"{title}\n{snippet}"
    names = [identity.canonical_name, *identity.aliases]
    named = any(
        _literal(name, text) and _identity_specific(name, identity.canonical_name)
        for name in names
    )
    identifier_match = any(_literal(value, text) for value in identity.identifiers)
    # Discussions often omit the brand or insert punctuation into the name.
    # An exact distinctive model code plus another supplied name token is
    # enough to read the page; each finding still needs its applicability check.
    model_tokens = [token for token in _TOKEN.findall(identity.canonical_name)
                    if len(token) >= 5 and _distinctive_identifier(token)]
    other_tokens = _meaningful_tokens(identity.canonical_name) - {
        token.casefold() for token in model_tokens}
    code_match = any(_literal(token, text) for token in model_tokens)
    named = named or (code_match and bool(other_tokens & _meaningful_tokens(text)))
    if not (named or identifier_match):
        return False

    # Exclude only an explicitly labelled conflicting variant; incidental years
    # and unrelated numbers in reports do not invalidate an otherwise exact hit.
    if identity.variant and named:
        parts = _TOKEN.findall(_normalize(identity.variant))
        stated = re.search(
            r"(?<!\w)(?:model|version|rev(?:ision)?|series)\s+([^\W_]+)",
            text,
            re.IGNORECASE | re.UNICODE,
        )
        if len(parts) == 1 and stated and _normalize(stated.group(1)) != parts[0]:
            return False
    return True


def conflicting_identity(identity: ProductIdentity, text: str) -> bool:
    """Reject a named neighbouring version rather than trusting a model verdict.

    An explicit edition marker or mixed-digit token immediately after the exact model name
    is an unresolved suffix, unless the listing already supplied it. This is
    conservative: ambiguous comparison pages need evidence from a clear span.
    """
    structural = {"owner", "owners", "review", "reviews", "report", "reports",
                  "repair", "repairs", "manual", "specifications", "specs",
                  "user", "users", "the", "a", "an", "is", "was", "has", "had"}
    known = _meaningful_tokens(" ".join(
        [identity.canonical_name, identity.variant, *identity.aliases, *identity.identifiers]))
    phrase = r"\s+".join(re.escape(part) for part in identity.canonical_name.split())
    for match in re.finditer(r"(?<!\w)" + phrase + r"(?!\w)", text, re.IGNORECASE):
        following = re.match(r"[ \t]+([^\W_][\w./-]*)", text[match.end():], re.UNICODE)
        if not following:
            continue
        token = following.group(1).rstrip(".,:;")
        folded = token.casefold()
        if folded in structural or folded in known:
            continue
        modifiers = {"pro", "plus", "max", "mini", "ultra", "lite", "gen",
                     "generation", "mk", "rev", "revision", "edition", "series"}
        if folded in modifiers or _distinctive_identifier(token) or token.isdigit():
            return True
    return False
