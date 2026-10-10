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


def gather(search, fetch, queries, *, seen: set, searched: set,
           limit: int, hits_per_query: int, say=None, check=None,
           parallel: bool = False):
    """One round: pages found by these queries and not read before.

    ``seen`` grows with every url this run has read (or failed to read — a
    page that refused the run once is not asked twice); ``searched`` grows
    with every query this run has searched, so the second round pays only for
    queries the first never asked. Returns ``(pages, wanted)`` where
    ``wanted`` is the urls this round tried, for the log line.
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
    for hits, failure in results:
        if check is not None:
            check()
        if failure and say is not None:
            say(failure)
        for hit in hits:
            url = str(hit.get("url", "")).strip()
            if not url or url in seen or len(wanted) >= limit:
                continue
            seen.add(url)
            wanted.append(url)
    if not wanted:
        return [], []
    return fetch_pages(fetch, wanted, say=say), wanted


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
