"""Content-addressed IDs.

Every row in a pack is keyed by a hash of its own content. That is what lets two
packs merge with a plain `INSERT OR IGNORE` and no conflict-resolution code.

Be precise about what this buys, because it is easy to overclaim:

  * It fires reliably for `sources` and `evidence` — URLs and verbatim quotes
    genuinely repeat across packs.
  * It fires for `attributes` and `subjects` when two authors normalise the same
    way, which `_norm` below is entirely about maximising.
  * It fires RARELY for `claims`. The live catalog already holds three separate
    LLM-authored titles for one physical EGR failure, produced by the same
    pipeline. Two independent packs will produce three more.

So: content hashing is *storage* identity. Title-similarity clustering at read
time (`title_sim`) is *presentation* identity, and it is load-bearing, not an
optimisation. Two subjects that hash differently because their authors disagreed
about identity keys are reconciled by the lookup path's attribute-overlap
matching, never by pretending the hashes agree.
"""

import hashlib
import json
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Bumped only for a deliberate, repo-wide re-hash. Every id changes when it does.
HASH_NAMESPACE = "kriko/v1"
ID_WIDTH = 32

_WS = re.compile(r"\s+")
# "1,395" / "1 395" / "1395.0" all mean the same number.
_NUMERIC = re.compile(r"^[+-]?[\d\s,]*\.?\d+$")
# Analytics parameters carry no identity; dropping them merges the same page
# reached through different links, so its quotes corroborate instead of splitting.
_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "mc_", "ref_", "igshid", "_hsenc")


def _norm(value) -> str:
    """Canonical string form of a value, for hashing only.

    Casefold + NFKC + whitespace squash, plus numeric canonicalisation so that
    `"1,395"`, `"1 395"` and `1395` are one value rather than three.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = unicodedata.normalize("NFKC", str(value)).strip()
    text = _WS.sub(" ", text)
    if _NUMERIC.match(text):
        stripped = text.replace(",", "").replace(" ", "")
        try:
            number = float(stripped)
        except ValueError:
            pass
        else:
            # Integers must not hash as "1395.0"; floats keep their precision.
            return str(int(number)) if number.is_integer() else repr(number)
    return text.casefold()


def _norm_title(text: str) -> str:
    """Titles additionally lose punctuation — word order still matters."""
    folded = _norm(text)
    return _WS.sub(" ", re.sub(r"[^\w\s]", " ", folded)).strip()


def normalize_url(url: str) -> str:
    """Drop the parts of a URL that are not identity.

    Scheme and host casing, a trailing slash, the fragment, and tracking
    parameters are all noise. Meaningful query parameters are kept — a YouTube
    video id lives in `?v=`, and dropping it would merge unrelated videos.
    """
    parts = urlsplit(url.strip())
    query = urlencode(
        sorted(
            (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if not k.lower().startswith(_TRACKING_PREFIXES)
        )
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def _hash(kind: str, payload) -> str:
    canon = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    body = f"{HASH_NAMESPACE}/{kind}\n{canon}".encode("utf-8")
    return hashlib.sha256(body).hexdigest()[:ID_WIDTH]


def subject_id(kind: str, identity: dict) -> str:
    """Hash a subject from its kind plus its identity attributes.

    `identity` is only the attributes the pack declared as identity-bearing, not
    every attribute the subject has — otherwise adding a `notes` field would
    mint a new subject.

    An author who includes `trim` in identity gets a different id from one who
    does not. That is intended: they are asserting different things about what
    makes a product distinct. The lookup path unions them by attribute overlap.
    """
    if not identity:
        raise ValueError(
            f"subject_id({kind!r}) needs at least one identity attribute — "
            "an empty identity would hash every subject of this kind together"
        )
    pairs = sorted((_norm(k), _norm(v)) for k, v in identity.items())
    return _hash("subject", {"kind": _norm(kind), "identity": pairs})


def attribute_id(
    subject_id: str,
    key: str,
    value,
    unit: str = "",
    valid_from: str = "",
    valid_to: str = "",
) -> str:
    """Hash one fact. The validity window is part of identity.

    A power figure that held 2014-2016 is a different fact from the same figure
    held 2017-2020, so a pack can carry both without one clobbering the other.
    """
    return _hash("attribute", {
        "s": subject_id, "k": _norm(key), "v": _norm(value),
        "u": _norm(unit), "f": _norm(valid_from), "t": _norm(valid_to),
    })


def relation_id(subject_id: str, predicate: str, object_id: str) -> str:
    """Hash an edge. Direction matters: `part_of` is not symmetric."""
    return _hash("relation", {"s": subject_id, "p": _norm(predicate), "o": object_id})


def source_id(url: str = "", text: str = "") -> str:
    """Hash a source by its normalised URL, or by its text when it has no URL.

    Sources without URLs are real — a manual, a scanned bulletin, a pasted
    document — and they still need a stable identity.
    """
    if url:
        return _hash("source", {"u": normalize_url(url)})
    if text:
        return _hash("source", {"h": hashlib.sha256(text.encode("utf-8")).hexdigest()})
    raise ValueError("source_id needs either a url or the source text")


def evidence_id(source_id: str, quote: str) -> str:
    """Hash a quote within a source, so the same quote from two packs collapses."""
    return _hash("evidence", {"src": source_id, "q": _norm(quote)})


def claim_id(subject_id: str, kind: str, domain: str, title: str, lang: str = "en") -> str:
    """Hash a claim. See the module docstring on why this rarely dedupes."""
    return _hash("claim", {
        "s": subject_id, "kind": _norm(kind), "domain": _norm(domain),
        "title": _norm_title(title), "lang": _norm(lang),
    })


def content_digest(row_ids) -> str:
    """Digest a whole pack from its sorted row ids.

    Deliberately NOT a checksum of the pack file: `zipfile` bakes in mtimes and
    entry ordering, so two builds of identical data would digest differently and
    break registry verification. Row ids are the content.
    """
    joined = "\n".join(sorted(row_ids))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
