"""What to search for, and what to say when the search found nothing.

A listing title is written for one marketplace in one language. Quoted whole
into a search for forum threads it finds nothing, because nobody writes it
that way. A part is discussed by its own name and the product it goes into,
in the language of the people discussing it. So the queries are built from the
identity's facets (the item in the search language, its maker, the product it
fits) and never from the title as one phrase.

Pure functions of an identity: no model call, no network, no category.
"""

from __future__ import annotations

import re

from app.providers.local_identity import ProductIdentity, fold, host_codes

#: What a reader of that language types to reach a discussion of a fault.
#: A small closed vocabulary of languages, not of products.
ISSUE_WORDS: dict[str, tuple[str, ...]] = {
    "en": ("problems owner reports forum", "failure troubleshooting discussion",
           "repair recurring fault", "long term issues forum"),
    "fr": ("problèmes utilisateurs forum", "panne discussion dépannage",
           "réparation défaut récurrent", "problèmes après utilisation forum"),
    "tr": ("sorun kullanıcı forum", "arıza çözüm tartışma",
           "tamir tekrarlayan arıza", "uzun kullanım sorunları forum"),
    "de": ("Probleme Nutzer Forum", "Defekt Diskussion Fehlerbehebung",
           "Reparatur wiederkehrender Fehler", "Langzeitprobleme Forum"),
    "es": ("problemas usuarios foro", "fallo discusión solución",
           "reparación defecto recurrente", "problemas uso prolongado foro"),
}

_YEAR = re.compile(r"^(?:19|20)\d{2}$")


def issue_words(language: str) -> tuple[str, ...]:
    return ISSUE_WORDS.get(language.split("-")[0].lower(), ISSUE_WORDS["en"])


def _host_core(identity: ProductIdentity) -> str:
    """The product it fits, without its model year, which pages rarely repeat."""
    words = [word for word in identity.fits.split() if not _YEAR.match(word)]
    return " ".join(words).replace("ı", "i").replace("İ", "I")


def part_queries(identity: ProductIdentity, language: str, limit: int = 4) -> list[str]:
    """Searches for discussions of a part that fits another product.

    Empty for a product that stands on its own, which keeps its own planner.
    """
    if not identity.dependent:
        return []
    item_terms = [term for term in identity.item_terms if term]
    item = f'"{item_terms[0]}"' if item_terms else f'"{identity.item}"'
    maker = identity.brand
    host = _host_core(identity)
    codes = host_codes(identity)
    code = codes[0] if codes else ""
    words = issue_words(language)
    # Each query leans on a different anchor, so one bad guess cannot empty the set.
    # The last is the part by its maker alone: faults that follow the part
    # across every product it fits are reported there.
    candidates = [
        f"{item} {maker} {host} {words[0]}",
        f"{item} {code or host} {words[1]}",
        f"{item} {host} {words[2]}",
        f"{item} {maker} {words[3]}",
    ]
    queries: list[str] = []
    for query in candidates:
        query = " ".join(query.split())
        if fold(query) not in {fold(one) for one in queries}:
            queries.append(query)
    return queries[:limit]


def nothing_read(coverage: dict, search_url: str = "") -> str:
    """Why no page came back, without blaming the connection for a bad match.

    Called only when not one page was read. Pages that were read and then
    judged to be about something else are an empty result, not an error.
    """
    searched = coverage.get("queries_searched", 0)
    failed = coverage.get("search_errors", 0)
    where = f" at {search_url}" if search_url else ""
    if failed and not searched:
        return (f"The search service{where} did not answer ({failed} of {failed} "
                "searches failed). Start OpenSERP or check its address in Settings, "
                "Local machine, then try again.")
    if not coverage.get("unique_hits"):
        return (f"The search service{where} answered but found no results for these "
                "queries. Try again later, or check that its search engines are "
                "not blocked from this connection.")
    return (f"{coverage['unique_hits']} results were found but none could be read "
            f"({coverage.get('pages_unreadable', 0)} blocked, empty or too slow). "
            "Check the internet connection and try again.")
