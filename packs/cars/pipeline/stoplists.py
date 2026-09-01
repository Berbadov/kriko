"""Curated stoplists for source discovery, code-family bookkeeping, and
language/verbosity checks over the extraction pipeline.

The claim-selection judgement this module used to carry (INSPECTION_COVERED,
GENERIC_MAINTENANCE_TERMS, AMBIGUOUS_INSPECTION_TERMS, WARNING_LIGHT_PATTERNS,
has_specificity_signal — read by the now-deleted gate_inspection_value in
judge.py) moved to packs/cars/vocabulary/gates.yaml, read through
kriko.gates. Those frozensets/function were a byte-for-byte duplicate with
zero importers once judge.py was deleted, so they were removed rather than
carried as dead weight — see the layering principle in CLAUDE.md.

FORUM_DOMAINS is used by the acquire stage to exclude forums from Exa discovery.
Forums surface a lot of genuine one-time/anecdotal issues that read like
chronic patterns once extracted — see pipeline_postmortem. Owner-club and
enthusiast-forum sites, and crowd-complaint boards, are all excluded; the
LLM gates can't reliably tell "this happened to one poster once" from "this
is a known chronic weak point" when the only source is a forum thread.

is_german_text is an interim source-language gate (2026-07-02): a non-.de
domain (what-breaks.com) served German-language pages that the extraction
LLM echoed verbatim into title/rationale/inspection_advice instead of
translating (megane4_body.yaml, ea288.yaml both have German claim text as a
result) — a domain blocklist can't catch this since the offending domain
isn't German-TLD. Keyword-density heuristic, not langdetect, to avoid a new
pipeline dependency — matches this file's existing regex/keyword approach.
Interim until extraction-time translation compliance is fixed properly.
"""

import re
from functools import lru_cache

from packs.cars.pipeline.paths import REPO_ROOT
from pathlib import Path
from urllib.parse import urlparse

from packs.cars.pipeline.util.yamlutil import load_yaml

# Failure words specific to machines with engines and drivetrains. These used
# to sit in kriko/ledger/chunking.py's FAILURE_LEXICON, which made the engine
# hold car vocabulary. Closed engineering vocabulary, so a constant is allowed
# per CLAUDE.md's scalability-principle exception.
CAR_FAILURE_TERMS: frozenset[str] = frozenset({
    "misfire", "judder", "shudder", "clog", "rattle",
})

# Engine/transmission code tokens (EA211, DQ200, K9K, H5H, R9M, DC4, ...): 1-4
# letters, a digit, then up to 3 more alphanumerics. Matches every code format
# used in this catalog's variant descriptors. Shared by promote.py's deterministic
# gate_variant bypass and has_variant_anchor below.
CODE_TOKEN_RE = re.compile(r"\b[A-Za-z]{1,4}\d[A-Za-z0-9]{0,3}\b")
_DISPLACEMENT_RE = re.compile(r"\b\d\.\d\s*(tsi|tdi|tfsi|dci|tce|sce|hdi|vti)\b", re.I)


def code_tokens(text: str) -> set[str]:
    """Uppercased engine/transmission code tokens found in text (EA211, DQ200, ...)."""
    return {t.upper() for t in CODE_TOKEN_RE.findall(text or "")}


# Same-manufacturer sibling component families: engineering codes that name a
# DIFFERENT physical part but get confused with each other because sources
# research them together (DSG comparison articles, engine-family
# retrospectives, "EDC" badge shared across generations). Live bug (see
# docs/design_flaws.md Flaw 1): DQ200 dry-clutch/accumulator claims (codes
# P189C/P17BF/P0841) filed under dq381.yaml (a wet-clutch gearbox that does
# not have those failure modes) because promote.py's deterministic bypass
# checks the full source page for ANY code match, and a DSG comparison
# article mentions "DQ381" somewhere too.
#
# History: this was a hand-maintained SIBLING_CODE_FAMILIES tuple (CLAUDE.md's
# scalability principle Flaw 1) — H5F/R9M/M9R went unrecognized because nobody
# remembered to add them to the separate list. Family membership is now
# declared per-part, via each part YAML's own `code_family` field (see
# catalog_sibling_families() below) — the same derive-from-catalog pattern as
# catalog_code_manufacturers().

# Part IDs follow a power-split convention (k9k_85, ea888_220, ...) — the
# trailing "_<hp>" is bookkeeping, not part of the engineering code. Also,
# CODE_TOKEN_RE's \b boundaries treat "_" as a word character, so
# code_tokens("ea888_220") finds nothing at all (no boundary between "8" and
# "_") — the suffix must be stripped before tokenizing, not just ignored.
# Mirrors packs/cars/pipeline/parts/search_templates.py's _search_code.
_PART_ID_POWER_SUFFIX_RE = re.compile(r"_\d+$")


def _part_base_code(part_id: str) -> frozenset[str]:
    return frozenset(code_tokens(_PART_ID_POWER_SUFFIX_RE.sub("", part_id)))


def sibling_codes_for(part_id: str) -> frozenset[str]:
    """Sibling codes for `part_id`'s family, excluding its own code(s).

    A power-tune-suffixed id like "ea888_220" resolves to its base code
    ("EA888") and finds its family. Empty if part_id isn't in any registered
    family (nothing to veto — most parts have no sibling-confusion risk).
    """
    own = _part_base_code(part_id)
    if not own:
        return frozenset()
    families = catalog_sibling_families()
    siblings: set[str] = set()
    for code in own:
        siblings |= families.get(code, frozenset())
    return frozenset(siblings) - own


# Leading alpha run of a component code — "DQ" of DQ200, "EA" of EA288. Two
# chars minimum: single-letter prefixes (H5F, K9K, R9M) are too ambiguous to key
# a family off, and would collide with sensor/DTC tokens (G28, N75, P0401).
_FAMILY_PREFIX_RE = re.compile(r"^[A-Z]{2,}")


def catalog_family_prefixes() -> frozenset[str]:
    """Family prefixes present in the catalog — {"DQ", "EA", "DC", "DW", ...}.

    Derived from the part YAMLs (catalog_code_manufacturers), so a newly
    onboarded family is recognised the moment its stub exists — no separate list
    to remember (CLAUDE.md's no-hardcoded-car-data rule).
    """
    return frozenset(
        m.group(0)
        for code in catalog_code_manufacturers()
        if (m := _FAMILY_PREFIX_RE.match(code.upper()))
    )


def uncatalogued_family_codes(text: str) -> frozenset[str]:
    """Codes in `text` that look like one of our families but name a component
    the catalog has never onboarded — DQ500 when we carry only DQ200/DQ250/DQ381.

    Such a code cannot be evidence about any part we serve: we have no fitment
    for it, so a claim citing it and nothing of ours is filed under the wrong
    part. Tokens with no catalog family prefix (DTC codes, sensor designations
    like G28/N75/P0401) are ignored — they are normal inside a claim about our
    own part.
    """
    catalogued = {c.upper() for c in catalog_code_manufacturers()}
    prefixes = catalog_family_prefixes()
    return frozenset(
        tok for tok in code_tokens(text)
        if tok not in catalogued
        and (m := _FAMILY_PREFIX_RE.match(tok))
        and m.group(0) in prefixes
    )


def mentions_sibling_code(text: str, part_id: str) -> bool:
    """True if `text` names a component code that is NOT `part_id`'s own — either
    a registered sibling (same family, different physical part: a DQ200
    dry-clutch claim filed under dq381.yaml) or an *uncatalogued* family code
    (DQ500, EA189 — a component we have never onboarded, so no claim citing only
    it can be about a part we serve).

    Own-code co-mention is treated as legitimate (a claim that names both codes,
    e.g. explicitly contrasting the two components, isn't the silent-mislabeling
    failure mode this guards against).
    """
    text_tokens = code_tokens(text)
    if text_tokens & _part_base_code(part_id):
        return False
    if text_tokens & sibling_codes_for(part_id):
        return True
    return bool(uncatalogued_family_codes(text))


# Manufacturer groups that legitimately co-mention each other's codes: badge-
# engineered siblings (Dacia is Renault's own brand — K9K/H4D/DC4 etc. are
# shared verbatim) and shared-platform group companies (VW Group's MQB-era
# engines/DSGs appear across Audi/Skoda/Seat/Cupra too). Single source of
# truth for both promote.py's brand-name guard and
# mentions_foreign_manufacturer_code below — a claim naming one of these
# isn't contamination, it's genuine shared-part evidence.
GROUP_SIBLINGS: dict[str, frozenset[str]] = {
    "renault": frozenset({"dacia"}),
    "volkswagen": frozenset({"audi", "skoda", "seat", "cupra"}),
}

_CATALOG_PARTS_DIR = REPO_ROOT / "packs" / "cars" / "data" / "parts"


@lru_cache(maxsize=1)
def catalog_code_manufacturers() -> dict[str, frozenset[str]]:
    """code -> manufacturer token(s), derived from every part YAML's own
    part_id + manufacturer field.

    Deliberately NOT a hand-maintained registry — a manually-updated list
    drifts the moment someone onboards a new engine code and forgets to
    register it anywhere (that design let H5F/R9M/M9R go unrecognized, docs/
    design_flaws.md remediation, 2026-07-05, and separately let
    SIBLING_CODE_FAMILIES go stale — see catalog_sibling_families() below,
    which replaced it the same way). Reading it off the catalog itself means
    a new part's code is covered the moment its stub exists
    (packs.cars.pipeline.parts.search_templates.generate_part_scaffold writes part_id +
    manufacturer before any research runs), with no separate registration
    step to forget. Cached — rebuild by calling
    catalog_code_manufacturers.cache_clear() if the catalog changes within a
    process lifetime (tests do this).
    """
    owners: dict[str, set[str]] = {}
    for path in sorted(_CATALOG_PARTS_DIR.glob("**/*.yaml")):
        data = load_yaml(path)
        part_id = data.get("part_id")
        manufacturer = data.get("manufacturer")
        if not part_id or not manufacturer:
            continue
        tokens = frozenset(str(manufacturer).lower().split("_"))
        for code in _part_base_code(part_id):
            owners.setdefault(code, set()).update(tokens)
    return {code: frozenset(makers) for code, makers in owners.items()}


@lru_cache(maxsize=1)
def catalog_sibling_families() -> dict[str, frozenset[str]]:
    """code -> sibling codes (same engineering family, excluding itself),
    derived from every part YAML's own `code_family` field (plus an optional
    `code_family_extra` list of known-sibling codes that don't have their own
    part file yet, e.g. M9R — declared once, on the part that discovered the
    relationship, e.g. r9m_130.yaml, rather than in a separate list).

    Replaces the old hand-maintained SIBLING_CODE_FAMILIES tuple (design_flaws.md
    Flaw 1) — same rationale as catalog_code_manufacturers() above: a part's
    family membership is covered the moment its own YAML declares it, with no
    separate cross-cutting registry to remember to update. Cached — rebuild by
    calling catalog_sibling_families.cache_clear() if the catalog changes
    within a process lifetime (tests do this).
    """
    groups: dict[str, set[str]] = {}
    for path in sorted(_CATALOG_PARTS_DIR.glob("**/*.yaml")):
        data = load_yaml(path)
        part_id = data.get("part_id")
        family = data.get("code_family")
        if not part_id or not family:
            continue
        codes = groups.setdefault(str(family), set())
        codes |= _part_base_code(part_id)
        for extra in data.get("code_family_extra") or []:
            codes.add(str(extra).upper())

    result: dict[str, set[str]] = {}
    for codes in groups.values():
        for code in codes:
            result.setdefault(code, set()).update(codes - {code})
    return {code: frozenset(siblings) for code, siblings in result.items()}


def mentions_foreign_manufacturer_code(text: str, own_makes: set[str]) -> bool:
    """True if `text` names an engine/transmission code registered anywhere
    in the catalog to a manufacturer other than one of `own_makes` or their
    GROUP_SIBLINGS.

    Complements mentions_sibling_code (same-manufacturer code confusion,
    e.g. DQ200 filed under dq381.yaml) and promote.py's OTHER_BRANDS guard
    (catches "Ford"/"Toyota" mentioned by brand name). Neither catches
    cross-manufacturer contamination expressed as code/tech jargon with no
    brand word at all — e.g. a Renault h4d_75 claim's rationale saying "the
    1.0 TSI (EA211) engine" never says "Volkswagen", so a brand-name check
    can't see it (live bug found 2026-07-05, see docs/design_flaws.md).
    """
    owners = catalog_code_manufacturers()
    if not owners:
        return False
    allowed = set(own_makes)
    for make in own_makes:
        allowed |= GROUP_SIBLINGS.get(make, frozenset())
    for token in code_tokens(text):
        makers = owners.get(token)
        if makers and not (makers & allowed):
            return True
    return False


def document_is_foreign_to_part(text: str, make: str, model: str) -> bool:
    """True if a fetched SOURCE DOCUMENT (not an extracted claim) is very
    likely entirely about a DIFFERENT manufacturer's part — names a
    foreign-manufacturer engine/transmission code and never mentions this
    part's own code or its own manufacturer anywhere in the text.

    `make`/`model` are passed straight through from
    packs.cars.pipeline.sources.curated.CuratedSource._fetch_entry's own parameters:
    for the part-centric pipeline, `model` IS the part_id
    (ops.process.run_part's "part_id doubles as model slug"
    convention) — resolved here via catalog_code_manufacturers(); for the
    model-centric pipeline, `model` won't resolve to a registered code, so
    `make` (already the real manufacturer name) is used directly. No signal
    on either side fails open — never exclude without a genuine mismatch.

    Runs at FETCH time, before a single extraction call is spent on the
    document. This is what mentions_foreign_manufacturer_code (claim-text
    level) and mentions_sibling_code both structurally can't catch: an
    extracted claim's own title/rationale can read as generic and plausible
    ("Connecting rod bearing failure") even though the SOURCE PAGE it was
    extracted from is 100% about a different engine entirely (found live in
    k9k_100.yaml's curated sources — several pages about VW's 1.5/1.6 TDI,
    not Renault's K9K — docs/design_flaws.md remediation, 2026-07-05).
    """
    owners = catalog_code_manufacturers()
    own_code = _part_base_code(model)
    if own_code and any(c in owners for c in own_code):
        own_makes: set[str] = set()
        for c in own_code:
            own_makes |= owners[c]
    else:
        own_makes = {make.lower()} if make else set()

    if not own_makes:
        return False

    text_tokens = code_tokens(text)
    if text_tokens & own_code:
        return False
    lowered = text.lower()
    if any(m and re.search(rf"\b{re.escape(m)}\b", lowered) for m in own_makes):
        return False
    return mentions_foreign_manufacturer_code(text, own_makes)


# Owner forums, enthusiast/club sites, and crowd-complaint boards.
FORUM_DOMAINS: frozenset[str] = frozenset({
    "forum.donanimhaber.com", "meganeownersclub.co.uk", "renaultforums.co.uk",
    "volkswagenforum.co.uk", "capturownersclub.co.uk", "vwaudiforum.co.uk",
    "daciaforum.co.uk", "qashqaiforums.co.uk", "vauxhallownersnetwork.co.uk",
    "en.volkswagenclub.net", "vwvortex.com", "team-bhp.com", "megane4-forum.de",
    "en.renault-club.cz", "forum.autodiagnostic.it", "vwforum.com.tr",
    "speakev.com", "forums.moneysavingexpert.com", "v-twinforum.com",
    "golftutkusu.com",
    # Crowd-complaint boards and ambiguous community/blog sites — reviewed
    # and confirmed for removal alongside the clear-cut forums above.
    "sikayetvar.com", "honestjohn.co.uk", "pistonheads.com",
    "otoclubturkiye.com", "arabakolik.net", "kroniksorunlar.net",
    "kronikuzman.com", "gaga.ba", "arizaisaretleri.com",
    # Stragglers caught by a forum/club/network keyword sweep of the corpus.
    "hyundaiclubtr.com", "forums.ross-tech.com", "carclubsusa.com",
    "otomobilforumlari.com", "forums.tdiclub.com", "forums.ybw.com",
    "hdforums.com", "mbclubtr.com", "nissan4x4ownersclub.com",
    "meganeelectricforums.com", "frenchcarforum.co.uk",
    # Surfaced by the "body" part-type queries (2026-07-02) — water-ingress
    # topics skew heavily toward forum anecdotes, so this axis needs the
    # blocklist extended more than most.
    "rmsmotoring.com", "golfmk7.com", "golfgtiforum.co.uk", "vwforum.nl",
    "motor-talk.de", "otopark.com", "uk-mkivs.net", "mk5golfgti.co.uk",
    "golfmk6.com", "vwroc.com", "r32oc.com", "community.cartalk.com",
    "meganesport.net", "rsmegane.com", "turborenault.co.uk",
    "renaultfanclub.com", "renaultsportclub.co.uk", "boards.ie",
    "diynot.com", "motorsforum.com", "justanswer.co.uk", "dhtauto.com",
    "howtomendit.com", "forum.rac.co.uk",
})

# Not forums — auto-generated "engine spec" content farms that state confident
# but factually wrong mechanical details (e.g. enginecode.uk describes the
# belt-driven Renault K9K 1.5 dCi as having a "timing chain"). Blocked as
# sources for the same reason as forums: the content can't be trusted, and a
# plausible-sounding factual error is harder to catch downstream than an
# obvious one. Separate constant from FORUM_DOMAINS so each stays semantically
# honest; is_blocked_source_domain() unions them.
UNRELIABLE_DOMAINS: frozenset[str] = frozenset({
    "enginecode.uk",
})


def is_blocked_source_domain(url_or_host: str) -> bool:
    """True if a URL or bare host resolves to a blocked source domain (forum or
    unreliable-content site). Matches the exact host or any subdomain of it, so
    'www.enginecode.uk' and 'm.enginecode.uk' are both caught."""
    host = url_or_host.lower()
    if "://" in host or "/" in host:
        host = urlparse(url_or_host).netloc.lower()
    host = host.removeprefix("www.")
    if not host:
        return False
    for blocked in FORUM_DOMAINS | UNRELIABLE_DOMAINS:
        if host == blocked or host.endswith("." + blocked):
            return True
    return False

# German function words with no English collision (word-boundary matched, so
# substrings like "ist" inside "list"/"exist" never hit). Used as a cheap
# language gate on fetched page/transcript text before it reaches extraction.
_GERMAN_MARKERS = re.compile(
    r"\b(und|nicht|auch|für|mit|wird|wurde|kann|können|müssen|sehr|über|eine|"
    r"einen|einer|ist|sich|oder|werden|sowie|diese|dieser|jedoch|allerdings|"
    r"während|dass|nach|noch|schon|besonders)\b",
    re.I,
)


def is_german_text(text: str, threshold: float = 0.02) -> bool:
    """Cheap heuristic: is this predominantly German-language text?

    German function-word density above `threshold` of total word count.
    Short texts (<20 words) fail open (return False) — too little signal to
    judge reliably, and we'd rather extract borderline content than drop it.
    """
    words = re.findall(r"[^\W\d_]+", text, re.UNICODE)
    if len(words) < 20:
        return False
    hits = len(_GERMAN_MARKERS.findall(text))
    return (hits / len(words)) > threshold


# Turkish/German-specific Latin letters that essentially never appear in
# English prose. Unlike is_german_text's function-word density check (needs
# ~20+ words to be reliable), a single occurrence of one of these characters
# in a short claim title is already strong signal — used by
# packs.cars.pipeline.translate_claims to catch untranslated titles too short for the
# density check (e.g. "IBS (Akü Sensörü) Arızalanması").
_NON_ENGLISH_CHAR_MARKERS = re.compile(r"[ğışçİÖÜÇŞĞäöüß]")


# Raw diagnostic trouble codes (OBD-II standard P0xxx/P1xxx, and 5-char
# manufacturer-extended forms like VW's P17BF/P189C). A title that leads
# with these instead of describing the general failure is noise a buyer
# can't act on without a scan tool — CLAUDE.md wants the general chronic
# pattern ("injector fouling"), not the code ("P0087"). The code itself is
# still useful to a mechanic, so it belongs in inspection_advice, not title.
# See packs/cars/pipeline/gold/gold.yaml's dtc_litany entries (added 2026-07-04 per
# user feedback: "not P0312 fail may cause x, we need just injector problems
# with brief descriptions").
DTC_CODE_RE = re.compile(r"\bP[0-9][0-9A-F]{3,4}\b", re.I)


def title_has_dtc_code(title: str) -> bool:
    """True if a raw diagnostic trouble code appears in the title — the
    general-failure description belongs in the title; the code belongs in
    inspection_advice."""
    return bool(DTC_CODE_RE.search(title or ""))


def has_variant_anchor(text: str) -> bool:
    """True if text names a genuine engine/transmission code or a
    displacement+fuel-tech label — the CLAUDE.md "config-specific" anchor a
    brief title still needs ("injector problems" is as useless as "brakes
    wear"; "injector fouling (K9K 1.5 dCi)" is the target).

    Deliberately excludes a plain code_tokens() check (the loose shape
    CODE_TOKEN_RE matches on its own): a DTC code (P1781, P0300) matches the
    SAME loose code-token shape as a
    real engine code (both are 1-4 letters + digit + alnum), so a DTC-litany
    title would otherwise look "anchored" by the very diagnostic code that's
    the problem. Only a non-DTC code token, or a displacement label, counts.
    """
    non_dtc_tokens = {t for t in code_tokens(text) if not DTC_CODE_RE.fullmatch(t)}
    return bool(non_dtc_tokens) or bool(_DISPLACEMENT_RE.search(text))


def title_is_verbose(title: str, max_len: int = 100) -> bool:
    """True if the title has collapsed into a full sentence/paragraph
    instead of a brief phrase. Caught live: a 490-char title that duplicated
    the claim's own rationale word-for-word (packs/cars/pipeline/translate_claims.py
    regression, fixed 2026-07-04) — titles this long are unreadable in a
    risk-card UI and signal the same "too narrow/technical" problem as a
    DTC-litany title, just via prose instead of codes."""
    return len(title or "") > max_len


def is_likely_non_english(text: str) -> bool:
    """Broader "is this not English" heuristic than is_german_text alone —
    catches Turkish (and German) text in short strings like claim titles by
    combining a character-marker check with the existing word-density check.
    """
    if _NON_ENGLISH_CHAR_MARKERS.search(text):
        return True
    return is_german_text(text)
