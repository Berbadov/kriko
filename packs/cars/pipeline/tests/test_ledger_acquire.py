"""Offline tests for ledger acquisition (discover → rank → fetch → ingest).

Every network-touching piece is injected: fake Exa client, fake page/transcript
fetchers. No real Exa/yt-dlp/trafilatura calls in tests.
"""

from types import SimpleNamespace

import pytest

from packs.cars.pipeline.ledger import acquire
from kriko.ledger import db

# ── rank_sources (backlog B8) ────────────────────────────────────────────────


def _r(url, title, type_="page"):
    return {"url": url, "title": title, "site_or_channel": url, "type": type_}


def test_rank_sources_prefers_code_specific_failure_titles():
    results = [
        _r("https://generic.test/a", "Used family cars reviewed"),
        _r("https://specific.test/b", "DW5 EDC7 gearbox problems and failures"),
        _r("https://mid.test/c", "Renault EDC7 reliability overview"),
    ]
    ranked = acquire.rank_sources(results, "dw5")
    assert ranked[0]["url"] == "https://specific.test/b"  # code + failure words
    assert ranked[1]["url"] == "https://mid.test/c"  # alias only
    assert ranked[2]["url"] == "https://generic.test/a"  # neither


def test_rank_sources_demotes_forums_below_editorial():
    forum_host = sorted(acquire.FORUM_DOMAINS)[0]
    results = [
        _r(f"https://{forum_host}/t/1", "DW5 EDC problems"),
        _r("https://editorial.test/x", "DW5 EDC problems"),
    ]
    ranked = acquire.rank_sources(results, "dw5")
    assert ranked[0]["url"] == "https://editorial.test/x"


# ── acquire_part end-to-end (injected network) ───────────────────────────────


class _FakeExa:
    def __init__(self, results_by_query):
        self.results_by_query = results_by_query
        self.calls = []

    def search(self, query, **kwargs):
        self.calls.append(query)
        return SimpleNamespace(
            results=[
                SimpleNamespace(url=u, title=t)
                for u, t in self.results_by_query.get(query, [])
            ]
        )


@pytest.fixture
def conn(tmp_path):
    return db.connect(tmp_path / "l.db")


def _exa_with(*pairs):
    # one query template -> [(url, title)]; unknown queries return []
    by_query = {}
    for query_frag, url, title in pairs:
        by_query.setdefault(query_frag, []).append((url, title))

    class E(_FakeExa):
        def search(self, query, **kwargs):
            self.calls.append(query)
            hits = [h for frag, hs in by_query.items() for h in hs if frag in query]
            return SimpleNamespace(
                results=[SimpleNamespace(url=u, title=t) for u, t in hits]
            )

    return E({})


def test_acquire_ingests_full_text_with_target_hint(conn):
    exa = _exa_with(("DW5", "https://a.test/dw5", "DW5 EDC7 problems"))
    big_text = "EDC7 gearbox failure discussion. " * 500  # > any old truncation cap
    s = acquire.acquire_part(
        conn,
        "dw5",
        "transmission",
        youtube=False,
        exa=exa,
        page_fetcher=lambda url: (big_text, ""),
    )
    assert s["ingested"] == 1
    row = conn.execute(
        "SELECT raw_text, target_hint, source_type FROM documents"
    ).fetchone()
    assert row["target_hint"] == "dw5"
    assert row["source_type"] == "page"
    assert row["raw_text"] == big_text  # no truncation anywhere


def test_acquire_skips_and_counts(conn):
    exa = _exa_with(
        ("DW5", "https://ok.test/1", "DW5 EDC7 problems"),
        ("DW5", "https://german.test/2", "DW5 EDC Getriebe Probleme"),
        ("DW5", "https://foreign.test/3", "DW5 EDC issues"),
        ("DW5", "https://dead.test/4", "DW5 EDC failures"),
    )
    pages = {
        "https://ok.test/1": "The DW5 EDC7 gearbox has clutch wear issues. " * 20,
        "https://german.test/2": (
            "Das Getriebe und der Kupplungsverschleiß sind bekannt. "
            "Viele Fahrer berichten von Schäden und undichten Dichtungen. " * 10
        ),
        # DQ200 is a Volkswagen code — foreign to a Renault part
        "https://foreign.test/3": "The DQ200 DSG mechatronic fails often. " * 20,
    }
    s = acquire.acquire_part(
        conn,
        "dw5",
        "transmission",
        youtube=False,
        exa=exa,
        page_fetcher=lambda url: (pages.get(url), ""),
    )
    assert s["ingested"] == 1
    assert s["skipped_german"] == 1
    assert s["skipped_foreign"] == 1
    assert s["skipped_fetch"] == 1
    assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 1


def test_acquire_dedups_across_runs(conn):
    exa = _exa_with(("DW5", "https://a.test/dw5", "DW5 EDC7 problems"))
    fetch = lambda url: ("EDC7 gearbox failure discussion. " * 50, "")
    s1 = acquire.acquire_part(
        conn, "dw5", "transmission", youtube=False, exa=exa, page_fetcher=fetch
    )
    s2 = acquire.acquire_part(
        conn, "dw5", "transmission", youtube=False, exa=exa, page_fetcher=fetch
    )
    assert s1["ingested"] == 1
    assert s2["ingested"] == 0
    assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 1


def test_acquire_threads_published_at_from_page_fetcher(conn):
    exa = _exa_with(("DW5", "https://a.test/dw5", "DW5 EDC7 problems"))
    s = acquire.acquire_part(
        conn, "dw5", "transmission", youtube=False, exa=exa,
        page_fetcher=lambda url: ("EDC7 gearbox failure discussion. " * 20,
                                  "2021-05-03"),
    )
    assert s["ingested"] == 1
    row = conn.execute("SELECT published_at FROM documents").fetchone()
    assert row["published_at"] == "2021-05-03"


def test_acquire_leaves_published_at_blank_when_fetcher_finds_none(conn):
    exa = _exa_with(("DW5", "https://a.test/dw5", "DW5 EDC7 problems"))
    s = acquire.acquire_part(
        conn, "dw5", "transmission", youtube=False, exa=exa,
        page_fetcher=lambda url: ("EDC7 gearbox failure discussion. " * 20, ""),
    )
    assert s["ingested"] == 1
    row = conn.execute("SELECT published_at FROM documents").fetchone()
    assert row["published_at"] == ""


def test_acquire_ranks_before_capping(conn):
    # 3 sources discovered, cap at 1: the code-specific failure title must win
    exa = _exa_with(
        ("DW5", "https://generic.test/a", "Used family cars reviewed"),
        ("DW5", "https://specific.test/b", "DW5 EDC7 gearbox problems"),
        ("DW5", "https://mid.test/c", "Renault EDC reliability"),
    )
    fetched = []
    s = acquire.acquire_part(
        conn,
        "dw5",
        "transmission",
        youtube=False,
        exa=exa,
        max_sources=1,
        page_fetcher=lambda url: (fetched.append(url) or "text " * 100, ""),
    )
    assert fetched == ["https://specific.test/b"]
    assert s["ingested"] == 1
