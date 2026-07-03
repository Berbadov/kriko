"""Curated stoplists for the inspection-value gate and source discovery.

INSPECTION_COVERED / WARNING_LIGHT_PATTERNS are used by gate_inspection_value
in judge.py to quickly reject claims that a standard pre-purchase mechanic
inspection already covers, or generic dashboard warning lights.

FORUM_DOMAINS is used by knowledge.auto (to exclude forums from future Exa
discovery) and by the one-off forum-source purge (knowledge/purge_forums.py).
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

# Items a standard pre-purchase mechanic inspection (ekspertiz) covers as routine.
# A claim matching any of these keywords is low value by the CLAUDE.md principle.
INSPECTION_COVERED: frozenset[str] = frozenset({
    # Fluids (inspector checks all fluid levels)
    "brake fluid", "coolant level", "oil level", "power steering fluid",
    "transmission fluid", "fluid level",
    # Brake wear (inspector measures pad/disc thickness)
    "brake pad", "brake disc", "brake rotor", "brake wear",
    # Injector bench tests (diesel specialist routine)
    "injector cleaning", "injector test", "injector bench", "injector flow test",
    # Compression (mechanic checks with gauge)
    "compression test",
    # Tire wear (visual inspection)
    "tire wear", "tyre wear",
    # Steering/suspension play (inspector checks all joints)
    "ball joint", "track rod", "tie rod", "wheel bearing play",
    # Clutch and manual gearbox (inspector test-drives — all caught on the road)
    "clutch wear", "clutch slip", "clutch drag", "synchro wear",
    "difficulty engaging gear", "grinding noise", "stuck in gear",
    "leaking gearbox oil", "gearbox oil leak",
    "selector fork", "synchromesh",
    # Exhaust visual (inspector checks for leaks/damage)
    "exhaust leak", "exhaust corrosion",
    # Generic gearbox symptoms (inspector test-drive catches these)
    "jerking in gear", "dropping out of gear", "burning smell from gearbox",
    # Generic system categories — too vague to act on; inspector covers these
    "brake system failure", "suspension failure", "steering system malfunction",
    "engine mounting", "engine mount",
    # Oil consumption / smoke — inspector sees on cold-start + road test + compression
    "oil consumption", "blue smoke", "burning oil",
    # Generic selector issues — inspector test-drives through all gears
    "difficulty selecting reverse", "cannot select reverse",
})

# Generic dashboard warning lights — true of any car, not this specific
# variant/config. A regex approach handles "ABS warning light", "ABS fault", etc.
WARNING_LIGHT_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\b(abs|esp|epc|dpf|scr|adblue)\s*(warning|light|fault|indicator)\b", re.I),
    re.compile(r"\b(check|engine|management)\s+(light|warning)\b", re.I),
    re.compile(r"\bdashboard\s+(warning|light)\b", re.I),
    re.compile(r"\bwarning\s+light\b", re.I),
)

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
