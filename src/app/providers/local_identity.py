"""Category-neutral, evidence-grounded product identity for local research."""

from __future__ import annotations

from dataclasses import dataclass, replace
import json
import re
import unicodedata
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
        "brand",
        "item",
        "item_terms",
        "fits",
    ],
    "properties": {
        "canonical_name": {"type": "string"},
        "aliases": {"type": "array", "items": {"type": "string"}},
        "variant": {"type": "string"},
        "identifiers": {"type": "array", "items": {"type": "string"}},
        "unknowns": {"type": "array", "items": {"type": "string"}},
        "brand": {"type": "string"},
        "item": {"type": "string"},
        "item_terms": {"type": "array", "items": {"type": "string"}},
        "fits": {"type": "string"},
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
    #: A part, accessory or consumable is not the product it fits. `item` is
    #: what is sold, `fits` the product it goes into, `item_terms` what the
    #: item is called in the search language (first) and in other languages.
    #: All empty for a product that stands on its own.
    brand: str = ""
    item: str = ""
    item_terms: tuple[str, ...] = ()
    fits: str = ""
    #: Every word of the reader's own product title, and each pair of
    #: neighbours run together (`500 GB` -> `500gb`). A page that says the
    #: model name followed by one of these is describing this product, not a
    #: neighbouring version of it. Never sent to a model (`as_dict`).
    stated: tuple[str, ...] = ()

    def prompt_dict(self) -> dict[str, Any]:
        """What a model needs to know, without empty fields or the quotes it was derived from.

        The local context is small and the task policy is not negotiable, so
        every byte of identity here is a byte of source evidence not shown.
        """
        full = self.as_dict()
        return {key: value for key, value in full.items()
                if value not in ("", [], ()) and key not in ("evidence", "source", "resolved")}

    @property
    def dependent(self) -> bool:
        """The subject is a part of something else, so that something else is context."""
        return bool(self.fits and (self.item or self.item_terms))

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
            "brand": self.brand,
            "item": self.item,
            "item_terms": list(self.item_terms),
            "fits": self.fits,
        }


def identity_prompt(product_prompt: str, listing_text: str = "", search_language: str = "") -> str:
    """Ask a small model for identity supported only by the provided text."""
    language = (f" in language {search_language}" if search_language else "")
    return f"""Extract exact product identity from the reader prompt and listing. Never guess model,
trim, year, size, revision, configuration, or identifier. Leave unsupported details empty and
state them in unknowns. Aliases and variant must be explicit in supplied text. Evidence quotes
must be verbatim.
Separate what is SOLD from what it belongs to. brand is the maker of the item, copied from the
text. If the product is a part, accessory, consumable or refill for ANOTHER product, then item is
the kind of part exactly as the text words it, fits is the other product it goes into (copy its
name, model, code and year from the text), and item_terms are 2 to 4 short names of that kind of
part{language} first, then in English; an item_terms name is a translation and may differ from the
text. If the product stands on its own, item, fits and item_terms are empty.
Return only one JSON object matching this schema:
{json.dumps(IDENTITY_SCHEMA, ensure_ascii=False)}

READER PRODUCT PROMPT (untrusted):
{product_prompt}

LISTING TEXT (untrusted):
{listing_text}"""


def fold(value: str) -> str:
    """Case, accents and the dotless i, so `Dcı` and `dCi` are one word."""
    text = unicodedata.normalize("NFKD", str(value).replace("ı", "i").replace("İ", "I"))
    return "".join(c for c in text if not unicodedata.combining(c)).casefold()


# Dashes, arrows, guillemets, bullets and separators a listing title ends with.
_EDGE_CHARS = "\\s\\-–—>→»›|:;,/·•*~<«‹"
_EDGE = re.compile(rf"^[{_EDGE_CHARS}]+|[{_EDGE_CHARS}]+$")


def clean_product_name(value: str) -> str:
    """A marketplace title without its arrows and separators at either end."""
    return _EDGE.sub("", " ".join((value or "").split()))


def _json_object(raw: str) -> dict | None:
    if not isinstance(raw, str):
        return None
    try:
        value = json.loads(raw.strip())
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _normalize(value: str) -> str:
    return " ".join(fold(value).split())


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


def stated_tokens(value: str) -> tuple[str, ...]:
    """The words of a product title as a page may spell them.

    Pages spell a size or a rating `500GB` where a listing says `500 GB`, so
    neighbouring words are also kept joined. Whole tokens only: a substring
    match would let `pro` pass because the title says `improved`.
    """
    words = _TOKEN.findall(_normalize(value))
    joined = [first + second for first, second in zip(words, words[1:])]
    return tuple(dict.fromkeys([*words, *joined]))


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
    name = clean_product_name(product_prompt or "") or "Unknown product"
    return ProductIdentity(canonical_name=name, unknowns=unknowns, resolved=False,
                           stated=stated_tokens(product_prompt or ""))


def _grounded(value: object, corpus: str) -> bool:
    """Every word of `value` is a word of the supplied text (nothing invented)."""
    if not isinstance(value, str) or not value.strip():
        return False
    known = set(_TOKEN.findall(_normalize(corpus)))
    words = _TOKEN.findall(_normalize(value))
    return bool(words) and all(word in known for word in words)


def _facets(data: dict, corpus: str) -> dict[str, Any]:
    """The brand, the item sold and the product it fits, each grounded in the text.

    `item_terms` is the one field that may be a translation, so it is not
    checked against the text; it only steers searches and the page filter,
    and every finding still has to pass its own evidence check.
    """
    def grounded(key: str) -> str:
        value = data.get(key)
        return " ".join(value.split()) if isinstance(value, str) and _grounded(value, corpus) else ""

    item = grounded("item")
    listed = data.get("item_terms")
    terms: list[str] = []
    for value in [*(listed if isinstance(listed, list) else []), item]:
        if not isinstance(value, str):
            continue
        term = " ".join(value.split())
        if (term and len(term) <= 40 and len(term.split()) <= 4
                and any(c.isalpha() for c in term) and term not in terms):
            terms.append(term)
    fits = grounded("fits")
    return {"brand": grounded("brand"), "item": item,
            "item_terms": tuple(terms[:5]) if fits else (),
            "fits": fits if fits and terms else ""}


def parse_identity(
    raw: str, product_prompt: str, listing_text: str = ""
) -> ProductIdentity:
    """Parse strict JSON and keep only identity strings literally grounded in input."""
    data = _json_object(raw)
    prompt = clean_product_name(product_prompt or "")
    if data is None:
        return _fallback(
            prompt, ("identity extraction failed", "exact variant")
        )
    required = set(IDENTITY_SCHEMA["required"][:6])
    optional = set(IDENTITY_SCHEMA["required"][6:])
    list_fields = ("aliases", "identifiers", "unknowns", "evidence")
    if not required <= set(data) <= required | optional or any(
        not isinstance(data.get(key), list) for key in list_fields
    ):
        return _fallback(
            prompt, ("identity response did not match schema", "exact variant")
        )

    corpus = f"{prompt}\n{listing_text or ''}"
    facets = _facets(data, corpus)
    name, variant = data.get("canonical_name"), data.get("variant")
    if (
        not isinstance(name, str)
        or not _literal(name, corpus)
        or not _identity_specific(name, prompt)
        or not isinstance(variant, str)
    ):
        # The name is the reader's own words; what the model still got right
        # about the item and what it fits is kept, because a dependent part
        # is searched and filtered by those and not by the whole title.
        return replace(_fallback(
            prompt,
            ("exact identity not verified from supplied text", "exact variant"),
        ), **facets)

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
        canonical_name=clean_product_name(name),
        aliases=aliases,
        variant=variant,
        identifiers=identifiers,
        unknowns=unknowns,
        evidence=evidence,
        resolved=bool(variant),
        source="listing text"
        if listing_text and (variant or identifiers)
        else "product prompt",
        stated=stated_tokens(product_prompt or ""),
        **facets,
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


def _mentions(term: str, text: str) -> bool:
    """The name as a phrase, or every word of it somewhere on the page.

    A translated name is rarely worded as the page words it (`filtre d'air`,
    `filtre à air`), so a name of two or more words also matches when each
    of its words is on the page.
    """
    if _literal(term, text):
        return True
    words = {word for word in _TOKEN.findall(_normalize(term)) if len(word) > 2}
    return len(words) >= 2 and words <= set(_TOKEN.findall(_normalize(text)))


def names_subject(identity: ProductIdentity, text: str) -> bool:
    """Whether the text names this product itself, by a name code can match.

    For a product that is its own subject only: a part's applicability hangs
    on what it fits, which a name on the page does not settle.
    """
    if identity.dependent or not identity.canonical_name.strip():
        return False
    return any(_mentions(term, text)
               for term in [identity.canonical_name, *identity.aliases, *identity.identifiers] if term)


def host_codes(identity: ProductIdentity) -> list[str]:
    """Letter-and-digit codes of the product the item fits (an engine, a series)."""
    return [token for token in _TOKEN.findall(identity.fits)
            if _distinctive_identifier(token)]


def _host_words(identity: ProductIdentity) -> set[str]:
    """Words of what the item fits that name it, not its year, count or size."""
    own = _meaningful_tokens(" ".join([identity.item, identity.brand, *identity.item_terms]))
    return {token for token in _meaningful_tokens(identity.fits)
            if not any(c.isdigit() for c in token) and token not in own}


def anchor_terms(identity: ProductIdentity) -> list[str]:
    """What marks a passage as about this subject, for choosing evidence windows.

    A part is anchored by its own names and its host's codes: its listing title
    is never copied word for word by the pages that discuss it.
    """
    terms = [identity.canonical_name, *identity.aliases, *identity.identifiers]
    if identity.dependent:
        terms = [*identity.item_terms, identity.item, *host_codes(identity)]
    return [term for term in dict.fromkeys(terms) if term]


def source_scope(identity: ProductIdentity, title: str = "", snippet: str = "") -> str:
    """How a page relates to the subject: `item`, `host_only` or `other`.

    For a part, a page about the product it fits is not a page about the part.
    The part's own name (in the reader's language or the search language) has
    to be on the page, with its maker or the product it fits beside it.
    """
    text = f"{title}\n{snippet}"
    terms =[*identity.item_terms, identity.item]
    has_item = any(_mentions(term, text) for term in terms if term)
    codes = host_codes(identity)
    words = _host_words(identity)
    page_words = _meaningful_tokens(text)
    has_host = (any(_literal(code, text) for code in codes) if codes
                else bool(words) and len(words & page_words) * 2 >= len(words))
    if has_host and codes and words:
        # A code alone (an engine) is not the host; its family name must show too.
        has_host = len(words & page_words) * 2 >= len(words) or len(codes) > 1
    has_brand = bool(identity.brand) and _literal(identity.brand, text)
    if has_item and (has_host or has_brand):
        return "item"
    return "host_only" if has_host else "other"


def relevant_source(
    identity: ProductIdentity, title: str = "", snippet: str = ""
) -> bool:
    """Require exact identity; allow owner reports without repeating variant detail.

    Word-boundary matching permits whitespace variation and Unicode names. A
    source that only matches a category or generic descriptor does not qualify.
    A part is judged by `source_scope`: its host's page is not its page.
    """
    if identity.dependent:
        return source_scope(identity, title, snippet) == "item"
    text = f"{title}\n{snippet}"
    names =[identity.canonical_name, *identity.aliases]
    named = any(
        _literal(name, text) and _identity_specific(name, identity.canonical_name)
        for name in names
    )
    identifier_match = any(_literal(value, text) for value in identity.identifiers)
    # Discussions often omit the brand or insert punctuation into the name.
    # An exact distinctive model code plus another supplied name token is
    # enough to read the page; each finding still needs its applicability check.
    # Three characters is a model code (`A54`, `S23`): a page about that phone
    # does not repeat the storage size and the colour a listing's title adds,
    # and requiring the whole title turned every such page away.
    model_tokens = [token for token in _TOKEN.findall(identity.canonical_name)
                    if len(token) >= 3 and _distinctive_identifier(token)]
    other_tokens = _meaningful_tokens(identity.canonical_name) - {
        _normalize(token) for token in model_tokens}
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


def scope_note(identity: ProductIdentity) -> str:
    """Tell a model that the item sold and the product it fits are two subjects."""
    if not identity.dependent:
        return ""
    item = identity.item_terms[0] if identity.item_terms else identity.item
    maker = f" made by {identity.brand}" if identity.brand else ""
    return (f"SCOPE: reviewed product = the {item}{maker}. It fits {identity.fits}, "
            f"which is context only: a fault of that product is NOT a finding "
            f"unless the source ties it to the {item}.")


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
        if folded in structural or folded in known or fold(token) in identity.stated:
            continue
        modifiers = {"pro", "plus", "max", "mini", "ultra", "lite", "gen",
                     "generation", "mk", "rev", "revision", "edition", "series"}
        if folded in modifiers or _distinctive_identifier(token) or token.isdigit():
            return True
    return False
