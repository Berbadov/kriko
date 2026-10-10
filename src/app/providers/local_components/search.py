"""The search rounds: queries in, pages out, side by side.

One round is: search each query, keep the urls worth reading, fetch them
together. The orchestrator may run two rounds (`local_agent.LocalAsker.ask`);
the state that makes rounds cooperate — urls already read, queries already
searched — is passed in by it and returned by here, so a round is a pure
function of its inputs and the second round cannot pay for the first round's
work twice.
"""

from concurrent.futures import ThreadPoolExecutor

from kriko.research.politeness import LocalSearchError

#: How much of a fetched page is kept before triage has its say. Generous on
#: purpose: triage needs the text to rank and to size, and the fetch is the
#: slow part, not the bytes.
RAW_CHARS = 40000

#: Pages read at once. Five pages fetched one after another on a cold
#: connection costs five round trips in sequence, which on a CPU-bound run is
#: the difference the reader feels.
AT_ONCE = 4


#: The most pages one site may supply to a run. A forum thread that tops every
#: query used to fill the whole reading list, so the model read one opinion
#: five times and called it research.
PER_HOST = 2

#: Candidates beyond `limit`, read only to replace a page that would not load.
SPARES = 3


def host_of(url: str) -> str:
    """The site a page belongs to: lower-cased, without a leading ``www.``."""
    from urllib.parse import urlsplit

    host = urlsplit(url).netloc.casefold().rsplit("@", 1)[-1]
    return host.removeprefix("www.")


def diversify(hit_lists, limit: int, *, seen: set, per_host: int = PER_HOST) -> list[str]:
    """Urls worth reading, one query's best hit after another's, a site at most `per_host` times.

    Taking each query's hits in order let the first query fill the list and
    let one site fill the rest. Round-robin by rank gives every query its best
    page before any gets its second, and the per-site cap makes the list a
    spread of sources rather than a depth of one. A url already in ``seen`` is
    skipped, and the ones chosen are added to it.
    """
    wanted: list[str] = []
    per_site: dict[str, int] = {}
    depth = max((len(hits) for hits in hit_lists), default=0)
    for rank in range(depth):
        for hits in hit_lists:
            if rank >= len(hits) or len(wanted) >= limit:
                continue
            url = str(hits[rank].get("url", "")).strip()
            site = host_of(url)
            if not url or url in seen or per_site.get(site, 0) >= per_host:
                continue
            seen.add(url)
            per_site[site] = per_site.get(site, 0) + 1
            wanted.append(url)
    return wanted


def gather(search, fetch, queries, *, seen: set, searched: set,
           limit: int, hits_per_query: int, say=None, check=None,
           parallel: bool = False):
    """One round: pages found by these queries and not read before.

    ``seen`` grows with every url this run has read (or failed to read — a
    page that refused the run once is not asked twice); ``searched`` grows
    with every query this run has searched, so the second round pays only for
    queries the first never asked. Returns ``(pages, wanted)`` where
    ``wanted`` is the urls this round tried, for the log line.

    The urls come from `diversify`, with `SPARES` beyond ``limit``: a page that
    will not load is replaced by the next candidate instead of leaving the
    run with fewer sources than it asked for.
    """
    wanted: list[str] = []
    pending = []
    for query in queries:
        low = query.casefold()
        if low in searched:
            continue
        searched.add(low)
        if check is not None:
            check()
        pending.append(query)

    def hits_for(query):
        try:
            return search(query, hits_per_query) or [], ""
        except LocalSearchError as error:
            return [], f"search failed for {query!r}: {error}"

    if parallel and len(pending) > 1:
        with ThreadPoolExecutor(max_workers=min(AT_ONCE, len(pending))) as pool:
            results = list(pool.map(hits_for, pending))
    else:
        results = []
        for query in pending:
            if check is not None:
                check()
            results.append(hits_for(query))
    for _, failure in results:
        if check is not None:
            check()
        if failure and say is not None:
            say(failure)
    wanted = diversify([hits for hits, _ in results], limit + SPARES, seen=seen)
    if not wanted:
        return [], []
    pages = fetch_pages(fetch, wanted[:limit], say=say)
    spares = wanted[limit:]
    while len(pages) < limit and spares:
        if check is not None:
            check()
        more = spares[:limit - len(pages)]
        spares = spares[len(more):]
        pages += fetch_pages(fetch, more, say=say)
    return pages, wanted


def fetch_pages(fetch, urls, *, say=None) -> list[tuple[str, str]]:
    """The pages that answered, in the order their urls were named.

    An unreadable page is a miss, never a failure: a store that 403s a
    reader is one less source, not a run that ends.
    """
    def _one(url: str) -> tuple[str, str]:
        try:
            got = fetch(url)
        except Exception:  # noqa: BLE001 - an unreadable page is a miss
            return url, ""
        text = getattr(got, "text", got) or ""
        return url, str(text).strip()[:RAW_CHARS]

    pages: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=min(AT_ONCE, len(urls))) as pool:
        for url, text in pool.map(_one, urls):
            if text:
                pages.append((url, text))
    if say is not None and len(pages) < len(urls):
        say(f"{len(urls) - len(pages)} page(s) would not be read")
    return pages
