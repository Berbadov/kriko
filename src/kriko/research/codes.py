"""Deterministic matching for catalog codes, so no socket has to be trusted.

A code is whatever string a pack uses to name one configuration of a subject
("EA288", "DHP484", a chassis mark, a revision suffix). Codes from the wild —
a scraped page, a socket's reply, a person typing — arrive noisy, and the
expensive failure is not a miss but a *false merge*: `860` folded into `861`
looks like a typo fix and quietly attaches evidence to the wrong thing.

The rule that prevents it, taken from the entity-drift literature: the digit
core of a code must match *exactly* before anything else is judged. Digits are
how catalogs say "different part"; no similarity threshold is allowed to
smooth across them. The alphabetic remainder may then be judged loosely —
spelling varies, punctuation is a storage detail.

The matcher never invents. Its whole output is either an exact hit against
codes the pack already knows, or a ranked shortlist of candidates for a
caller to choose from. Anything else — including "close enough" — is
`NO_MATCH`, on purpose: an uncertain code is a question for the caller, not a
decision the matcher makes silently.
"""

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

#: Punctuation catalogs use as decoration inside a code. Storage detail.
_SEPARATORS = re.compile(r"[\s\-_/.,:;()\\]+")

#: Anything that is not a letter or a digit after folding is noise.
_ALNUM = re.compile(r"[^a-z0-9]+")

#: Unicode digits a keyboard or a copy-paste can substitute for ASCII.
_DIGIT_FOLD = {
    "\u0660": "0", "\u0661": "1", "\u0662": "2", "\u0663": "3", "\u0664": "4",
    "\u0665": "5", "\u0666": "6", "\u0667": "7", "\u0668": "8", "\u0669": "9",
    "\u06f0": "0", "\u06f1": "1", "\u06f2": "2", "\u06f3": "3", "\u06f4": "4",
    "\u06f5": "5", "\u06f6": "6", "\u06f7": "7", "\u06f8": "8", "\u06f9": "9",
    "\uff10": "0", "\uff11": "1", "\uff12": "2", "\uff13": "3", "\uff14": "4",
    "\uff15": "5", "\uff16": "6", "\uff17": "7", "\uff18": "8", "\uff19": "9",
}

#: Match outcomes. `EXACT` is the only one a caller may act on without
#: asking anybody; `CANDIDATES` means "pick from this shortlist or refuse";
#: `NO_MATCH` means the code is new, and new is a fact, not an error.
EXACT = "exact"
CANDIDATES = "candidates"
NO_MATCH = "no_match"

#: How many candidates a caller can meaningfully choose between. Beyond a
#: handful the honest answer is that nothing matched.
MAX_CANDIDATES = 4

#: Similarity a code-without-digits must reach to be a candidate at all.
#: Low on purpose: candidates are *questions*, and the caller — a person or
#: a constrained socket — is the one who answers them.
_MIN_SIMILARITY = 0.75


def normalize(raw: str) -> str:
    """The comparable form of a code: folded, stripped, separators gone."""
    if not raw:
        return ""
    text = unicodedata.normalize("NFKC", str(raw)).casefold()
    for needle, plain in _DIGIT_FOLD.items():
        text = text.replace(needle, plain)
    text = _SEPARATORS.sub("", text)
    return _ALNUM.sub("", text)


def digit_core(normalized: str) -> str:
    """Just the digits. Must match exactly for two codes to be relatives."""
    return "".join(char for char in normalized if char.isdigit())


def alpha_remainder(normalized: str) -> str:
    """Just the letters. Judged loosely, and only after the digits agreed."""
    return "".join(char for char in normalized if char.isalpha())


@dataclass(frozen=True)
class Resolution:
    """What `resolve` decided. Never silent, never a guess.

    `code` is set on EXACT and is the catalog's own spelling, not the raw
    input's — evidence must attach to what the pack knows, not to what a
    page happened to type. `candidates` carries `(similarity, code)` pairs,
    best first, and is empty unless the outcome is CANDIDATES.
    """
    outcome: str
    code: str = ""
    candidates: tuple[tuple[float, str], ...] = ()

    @property
    def is_exact(self) -> bool:
        return self.outcome == EXACT


def resolve(raw: str, known: tuple[str, ...] = (), *, normalized_known=None) -> Resolution:
    """Match one wild code against the codes a pack already knows.

    `known` is the catalog's spelling; pass `normalized_known` when the same
    catalog is resolved against repeatedly, so folding happens once.

    Three outcomes, one guarantee: a different digit core is never merged
    and never even offered — `M271.860` against a catalog holding `M271.861`
    is NO_MATCH, because the digits disagree and no amount of letter
    similarity is allowed to overrule them.
    """
    folded = normalize(raw)
    if not folded:
        return Resolution(NO_MATCH)
    catalog = normalized_known
    if catalog is None:
        catalog = {normalize(code): code for code in known if normalize(code)}
    hit = catalog.get(folded)
    if hit is not None:
        return Resolution(EXACT, code=hit)

    raw_digits = digit_core(folded)
    scored: list[tuple[float, str]] = []
    for other, spelling in catalog.items():
        if not other:
            continue
        if raw_digits and digit_core(other):
            if digit_core(other) != raw_digits:
                continue
            score = 1.0 if other == folded else SequenceMatcher(
                None, folded, other).ratio()
        else:
            score = SequenceMatcher(None, folded, other).ratio()
            if score < _MIN_SIMILARITY:
                continue
        if score >= _MIN_SIMILARITY:
            scored.append((score, spelling))
    scored.sort(key=lambda pair: (-pair[0], pair[1]))
    if scored:
        return Resolution(CANDIDATES, candidates=tuple(scored[:MAX_CANDIDATES]))
    return Resolution(NO_MATCH)


def extract_codes(text: str, known: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Codes worth resolving, out of scraped prose. Order of appearance.

    Two sources, both cheap and neither clever: strings that look like a
    known code after folding (a catalog's spelling varies in the wild), and
    bracketed uppercase alphanumerics of 3+ characters, which is the shape
    most catalogs use for a revision or family mark. Nothing here *decides*
    anything — it hands `resolve` raw material, and `resolve` refuses to
    guess.
    """
    if not text:
        return ()
    catalog = {normalize(code): code for code in known if normalize(code)}
    seen: list[str] = []
    taken: set[str] = set()
    for match in re.finditer(r"\b[A-Z][A-Z0-9.\-]{2,15}\b", text):
        token = match.group(0)
        folded = normalize(token)
        if not folded:
            continue
        spelling = catalog.get(folded)
        if spelling is None:
            if not re.search(r"\d", folded) or not catalog:
                continue
            if not any(digit_core(folded) == digit_core(other)
                       for other in catalog):
                continue
            spelling = token
        if spelling not in taken:
            taken.add(spelling)
            seen.append(spelling)
    return tuple(seen)
