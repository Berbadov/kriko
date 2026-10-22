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
import urllib.parse

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

#: How a search engine is asked for each kind of source the reader can pick
#: on the Agents tab (`prefs.SOURCE_KINDS`). A closed vocabulary of where
#: evidence comes from, true of any category: no product appears in it. The
#: forum angle is the language's own `issue_words`, so it is not listed here.
KIND_TERMS: dict[str, str] = {
    "reviews": "long term review problems",
    "recalls": "recall service bulletin official notice",
    "manufacturer": "official manual specifications",
    "video": "video review teardown problems",
    "news": "news problems reported",
}

#: The one closed vocabulary of *kinds of source*, in the order a plan tries
#: them: the same six the Agents tab offers (`prefs.SOURCE_KINDS`), named by
#: what they are in a job log and in a brief. It is where evidence comes from,
#: never what the evidence is about, so no category and no product appears in
#: it (CLAUDE.md's exception).
SOURCE_KINDS: dict[str, str] = {
    "forums": "owner forums and discussion threads",
    "reviews": "professional reviews and long-term tests",
    "news": "news reports",
    "recalls": "recalls, service bulletins and official notices",
    "manufacturer": "the manufacturer's own documentation",
    "video": "video reviews and teardowns",
}
KIND_ORDER: tuple[str, ...] = tuple(SOURCE_KINDS)

#: What a question says when it is asking for a kind of source. A closed
#: vocabulary of *questions*, in the languages `ISSUE_WORDS` holds, and true of
#: any product: it is what a reader asks ("what did owners report?", "is there a
#: recall?"), never what they ask about.
KIND_ASKS: dict[str, str] = {
    "forums": (
        r"owner|owners|owner'?s|forum|forums|thread|threads|community|communities|"
        r"discussion|discussions|experience|experiences|reliab\w*|real.?world|"
        r"problem|problems|issue|issues|fail|fails|failed|failure|failures|fault|faults|"
        r"complain\w*|broken|defect|defects|repair|troubleshoot\w*|"
        r"kullanıcı|sorun\w*|arıza\w*|tamir|panne|probl[eè]me\w*|d[ée]faut\w*|"
        r"r[ée]par\w*|utilisateur\w*|fehler|defekt\w*|reparatur|nutzer|"
        r"fallo\w*|problema\w*|reparaci[óo]n|usuario\w*"
    ),
    "reviews": (
        r"review|reviews|tested|test|tests|long.?term|durability|teardown|"
        r"magazine|expert|critique|essai|testbericht|rezension|an[áa]lisis|inceleme"
    ),
    "news": r"news|reported|press|article|articles|coverage|journal|noticia|haber|nachrichten",
    "recalls": (
        r"recall|recalls|safety|hazard\w*|bulletin|bulletins|service notice|"
        r"official notice|notice|campaign|regulator\w*|nhtsa|rappel|r[üu]ckruf|"
        r"retirada|geri çağırma|g[üu]venlik"
    ),
    "manufacturer": (
        r"specification|specifications|specs|datasheet|manual|manuals|documentation|"
        r"document|documents|manufacturer|maker|official|compatib\w*|datasheets?|"
        r"fiche technique|manuel|handbuch|technische daten|kılavuz|teknik [öo]zellik"
    ),
    "video": r"video|videos|youtube|teardown video|watch|clip|vlog",
}

#: What a query that already *names* a kind looks like — the words a search
#: engine reads as that kind of page. Deliberately narrower than `KIND_ASKS`:
#: a query can ask for owner reports ("problems owner reports") without ever
#: saying the word an engine matches threads on, which is what the marker below
#: adds, and why this list does not contain "owner reports".
KIND_MARKS: dict[str, str] = {
    "forums": r"\b(?:forums?|threads?|boards?|communities|community|subreddit|discussion|"
              r"discussions)\b|/r/|/comments/",
    "reviews": r"\b(?:reviews?|long.?term|teardown|test(?:ed)?|magazine)\b",
    "news": r"\b(?:news|press|reported)\b",
    "recalls": r"\b(?:recalls?|service bulletins?|official notices?|safety)\b",
    "manufacturer": r"\b(?:manuals?|specifications?|specs|datasheets?|documentation|"
                    r"manufacturer)\b",
    "video": r"\b(?:videos?|youtube|teardown)\b",
}

#: What a question that named no kind is searched for, in this order. The
#: engine's whole question is what goes wrong with one product, so owner
#: reports come first; the angles behind them are `DEFAULT_ANGLES`.
DEFAULT_KINDS: tuple[str, ...] = ("forums", "reviews", "manufacturer")

#: What a quick look asks when the reader picked no kind: owner reports, a
#: review angle, and the manual for the figures a buyer compares.
DEFAULT_ANGLES = ("problems owner reports", "failures review",
                  "specifications manual recalls")

_YEAR = re.compile(r"^(?:19|20)\d{2}$")


def quick_angles(kinds: list[str] | tuple[str, ...] = (), language: str = "en",
                 limit: int = 3) -> list[str]:
    """The words to add to a product's name for each quick-look search.

    The reader's picked kinds come first, in the order the Agents tab lists
    them, each as its own search so one kind cannot crowd out another. What is
    left of `limit` is filled from the defaults, because "go to these first"
    never meant "ask nowhere else". Without kinds in English this is the
    fixed default set; in another language the owner-report angles are that
    language's own words.
    """
    words = issue_words(language)
    base = (DEFAULT_ANGLES if language.split("-")[0].lower() == "en"
            else (words[0], words[1], DEFAULT_ANGLES[2]))
    chosen: list[str] = []
    for kind in kinds:
        angle = words[0] if kind == "forums" else KIND_TERMS.get(kind, "")
        if angle and angle not in chosen:
            chosen.append(angle)
    for angle in base:
        if len(chosen) >= limit:
            break
        if angle not in chosen:
            chosen.append(angle)
    return chosen[:limit]


def issue_words(language: str) -> tuple[str, ...]:
    return ISSUE_WORDS.get(language.split("-")[0].lower(), ISSUE_WORDS["en"])


# ── the agent's choice of source kinds ───────────────────────────────────────

def kind_terms(kind: str, language: str = "en") -> str:
    """The words that ask a search engine for this kind, in this language."""
    if kind == "forums":
        return issue_words(language)[0]
    return KIND_TERMS.get(kind, "")


def choose_kinds(question: str, *, limit: int = 3, default: tuple = ()) -> list[str]:
    """The kinds of source this question asks for, in the order they are tried.

    **The agent's decision, as a pure function**: it reads the question's own
    words against `KIND_ASKS`, a closed vocabulary of what asking for a kind of
    evidence sounds like in any category ("what did owners report?", "is there a
    recall?", "what does the manual say?"). A question that asks for nothing in
    particular answers `default`, which is how a caller fails open to its own
    standing angles.
    """
    text = fold(str(question or ""))
    found = [kind for kind in KIND_ORDER if re.search(KIND_ASKS[kind], text)]
    return (found or list(default))[:max(1, limit)]


def kind_of(query: str, language: str = "en") -> str:
    """The kind of source this one query targets, or "" when it asks for none."""
    found = [kind for kind in choose_kinds(query, limit=len(KIND_ORDER))
             if re.search(KIND_MARKS[kind], fold(query))]
    if found:
        return found[0]
    return ""


#: The one word that asks an engine for a kind without naming its whole angle.
#: The forum word comes from the language itself (`kind_marker`): every entry of
#: `ISSUE_WORDS` ends in that language's word for a forum.
KIND_MARKERS: dict[str, str] = {
    "reviews": "review",
    "news": "news",
    "recalls": "recall",
    "manufacturer": "manual",
    "video": "video",
}


def kind_marker(kind: str, language: str = "en") -> str:
    """The one word that asks an engine for this kind, in this language."""
    if kind == "forums":
        words = issue_words(language)[0].split()
        return words[-1] if words else ""
    return KIND_MARKERS.get(kind, "")


def marked_query(query: str, kind: str, language: str = "en") -> str:
    """A query searched for this kind: its own words, plus the kind's marker.

    For a question ("what did owners report about X?") the whole angle phrase
    would read as noise; one word is what a person types to reach a thread, and
    the measurably different answer an engine gives for it — a query asking for
    owner reports without the word "forum" returns review and data-recovery
    pages beside the threads, the same query with it returns the threads first —
    is the reason the query is changed at all. A query that already names the
    kind is left alone, and the words actually searched are the words logged.
    """
    text = " ".join(str(query or "").split())
    if kind not in SOURCE_KINDS or re.search(KIND_MARKS[kind], fold(text)):
        return text
    marker = kind_marker(kind, language)
    return f"{text} {marker}".strip() if marker else text


def plan_queries(queries, kinds, *, subject: str = "", language: str = "en",
                 limit: int = 4) -> tuple[list[str], list[str]]:
    """`(queries, kinds)`: the searches for a chosen set of kinds, labelled.

    The agent's decision, applied without inventing anything. A query that
    already names a kind is kept and labelled with it; a query that *asks* for
    a chosen kind without naming it ("problems owner reports" asks for owner
    reports, and no engine reads that as a thread) is given that kind's marker
    word — which is the measured difference between a page set with threads at
    the top and one with data-recovery pages in it. A kind still unaccounted
    for takes over a query that merely repeats a kind already covered, and a
    plan with no queries at all is given one per kind. Nothing else changes the
    words a planner chose, and the label per query is what makes the decision
    observable: it is the kind the log line prints and the kind a reader can
    filter a run's steps by.
    """
    out: list[str] = []
    labels: list[str] = []
    for query in queries:
        text = " ".join(str(query or "").split())
        if text:
            out.append(text)
            labels.append(kind_of(text, language))
    for kind in [one for one in kinds if one in SOURCE_KINDS]:
        if kind in labels:
            continue
        target = _asks_kind(out, labels, kind)
        if target is None:
            target = _repeated_kind(labels)
        if target is None:
            words = kind_terms(kind, language)
            if not out and subject and words:
                out.append(f'"{subject}" {words}')
                labels.append(kind)
            continue
        out[target] = marked_query(out[target], kind, language)
        labels[target] = kind
    return out[:limit], labels[:limit]


def _asks_kind(queries: list[str], labels: list[str], kind: str) -> int | None:
    """The first query that asks for `kind` without naming it, if there is one."""
    for index, query in enumerate(queries):
        if labels[index]:
            continue
        if kind in choose_kinds(query, limit=1):
            return index
    return None


def _repeated_kind(labels: list[str]) -> int | None:
    """The later of two queries that name the same kind, if there is one."""
    seen: set[str] = set()
    for index, label in enumerate(labels):
        if not label:
            continue
        if label in seen:
            return index
        seen.add(label)
    return None


def kinds_line(kinds) -> str:
    """The decision as one log line: `searching kinds: forums, reviews`."""
    named = [kind for kind in kinds if kind in SOURCE_KINDS]
    return "searching kinds: " + ", ".join(named) if named else ""


def searched_line(kind: str, query: str, hits=(), failure: str = "") -> str:
    """One search as a job-log step: which kind, which words, what came back.

    The shape is a contract, not prose: `web.steps.classify` reads a line
    beginning `searched` as a search step, so a run's source selection can be
    filtered and read rather than guessed at. The kind is on the line, the
    words are on the line, and what came back is either the sites that answered
    or why nothing did.
    """
    head = (f"searched kind {kind}: {query}" if kind in SOURCE_KINDS
            else f"searched: {query}")
    hosts = _hosts(hits)
    if hosts:
        return f"{head} -> search returned {len(hits)} result(s) at {', '.join(hosts)}"
    if failure:
        return f"{head} -> search returned nothing ({failure})"
    return f"{head} -> search returned nothing"


def _hosts(hits, limit: int = 4) -> list[str]:
    """The sites an answer came from, in the order the search returned them."""
    found: list[str] = []
    for hit in hits or ():
        if not isinstance(hit, dict):
            continue
        site = str(hit.get("site") or "").strip()
        if not site:
            site = urllib.parse.urlsplit(str(hit.get("url") or "")).netloc
        site = site.casefold().removeprefix("www.")
        if site and site not in found:
            found.append(site)
        if len(found) >= limit:
            break
    return found


def attempts_said(attempts, limit: int = 6) -> str:
    """What each search provider said, as one sentence for the reader.

    The honest half of "no results": which doors were tried and what each one
    answered, read from the searcher's own record (`websearch.Chain.attempts`,
    `local_agent`'s coverage) rather than guessed at. Never a key: a provider
    reports hosts, statuses and engines, which is what the adapters already keep
    out of a query.
    """
    said: list[str] = []
    for row in attempts or ():
        if not isinstance(row, dict):
            continue
        name = str(row.get("label") or row.get("provider") or "the search service")
        why = " ".join(str(row.get("reason") or "").split())
        outcome = str(row.get("outcome") or "")
        if outcome == "ok" and not why:
            continue
        said.append(f"{name}: {why or outcome or 'nothing'}")
        if len(said) >= limit:
            break
    return "Providers tried — " + "; ".join(said) + "." if said else ""


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

    When the searcher kept its own record of the doors it tried
    (`coverage["search_attempts"]`), what each of them said is named too: "no
    results" is an answer a reader can act on only if it says who answered it.
    An empty result with no reason at all is the one thing this must not be.
    """
    searched = coverage.get("queries_searched", 0)
    failed = coverage.get("search_errors", 0)
    where = f" at {search_url}" if search_url else ""
    said = attempts_said(coverage.get("search_attempts"))
    tail = f" {said}" if said else ""
    if failed and not searched:
        return (f"The search service{where} did not answer ({failed} of {failed} "
                "searches failed). Start OpenSERP or check its address in Settings, "
                f"Local machine, then try again.{tail}")
    if not coverage.get("unique_hits"):
        return (f"The search service{where} answered but found no results for these "
                "queries. Try again later, or check that its search engines are "
                f"not blocked from this connection.{tail}")
    return (f"{coverage['unique_hits']} results were found but none could be read "
            f"({coverage.get('pages_unreadable', 0)} blocked, empty or too slow). "
            "Check the internet connection and try again.")
