"""One press: does the page this claim cites still say it?

The check is deliberately narrow — a substring, not a judgement — and these
tests hold the three things that make it safe to offer: it reads the pack's own
quote rather than the caller's, it never claims more than "the page says this
now", and it changes nothing in the engine's store.

`app/factcheck.py` explains why the matching is loose about whitespace and
case where `findings.py` is strict. The test for that is here, because it is
the difference between a useful button and one that cries wolf on every
curly apostrophe.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import factcheck
from app.web import state
from app.web.app import create_app
from app.web.settings import Settings
from kriko.store.db import connect

QUOTE = "the timing belt is due at 120,000 km"


def _store(path):
    conn = connect(path)
    # No `packs` row: this check reads claims and evidence, and a fixture
    # that installs a whole pack to test a substring would be testing the
    # installer instead.
    conn.execute(
        "INSERT INTO subjects (subject_id, pack_id, kind, label)"
        " VALUES ('s1', 'p', 'k', 'A thing')"
    )
    conn.execute(
        "INSERT INTO claims (claim_id, pack_id, subject_id, kind, domain,"
        " severity, created_at) VALUES ('c1', 'p', 's1', 'maintenance', 'd',"
        " 'high', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO claim_text (claim_id, pack_id, lang, title)"
        " VALUES ('c1', 'p', 'en', 'Belt due')"
    )
    conn.execute(
        "INSERT INTO sources (source_id, pack_id, url, domain)"
        " VALUES ('src', 'p', 'https://example.test/a', 'example.test')"
    )
    conn.execute(
        "INSERT INTO evidence (evidence_id, pack_id, claim_id, source_id, quote)"
        " VALUES ('e1', 'p', 'c1', 'src', ?)",
        (QUOTE,),
    )
    conn.commit()
    conn.close()


@pytest.fixture
def client(tmp_path):
    _store(tmp_path / "k.sqlite")
    app = create_app(
        Settings(
            store_path=tmp_path / "k.sqlite",
            app_state_path=tmp_path / "app.sqlite",
            analysis_log_path=tmp_path / "a.jsonl",
        )
    )
    with TestClient(app) as client:
        yield client


def _page(monkeypatch, text, error=""):
    monkeypatch.setattr(
        factcheck, "fetch", lambda url, opener=None: (text, error)
    )


# ── the check itself, with no socket ─────────────────────────────────────


def test_an_extractors_punctuation_is_not_a_missing_quote():
    """The stored quote came out of one extractor and the page is being read
    by another one years later. A curly apostrophe, a non-breaking space and a
    re-cased heading are artefacts of that, and reporting them as "the source
    no longer says this" would be a lie told confidently."""
    stored = "the owner's manual says 120,000 km"
    live = "<h2>The Owner’s Manual   says 120,000 km</h2>"
    page = factcheck.text_of(live.encode(), "text/html")
    assert factcheck.flatten(stored) in factcheck.flatten(page)


def test_the_script_body_is_not_the_page():
    """A quote found only inside a <script> is not on the page a reader sees —
    and JSON-LD blocks repeat half an article, so this is not hypothetical."""
    body = b"<p>visible</p><script>var s = 'the timing belt is due';</script>"
    text = factcheck.text_of(body, "text/html")
    assert "visible" in text
    assert "timing belt" not in text


def test_adjacent_elements_do_not_run_their_words_together():
    text = factcheck.text_of(b"<p>done</p><p>at 90k</p>", "text/html")
    assert "done at 90k" in " ".join(text.split())


def test_a_pdf_is_unreadable_rather_than_missing(monkeypatch):
    """Absence of proof, not proof of absence. A PDF source reported as
    `missing` would quietly accuse every manual-backed claim in a pack."""
    monkeypatch.setattr(
        factcheck,
        "fetch",
        lambda url, opener=None: (None, ""),
    )
    assert factcheck.check_source("q", "https://x.test/a")["verdict"] == "unreadable"


def test_a_file_url_is_refused_before_anything_is_read():
    """A pack is remote data. `file:///etc/passwd` in a source row would read
    the reader's disk on a pack author's say-so."""
    text, error = factcheck.fetch("file:///etc/passwd")
    assert text is None
    assert "http" in error


def test_one_confirmed_quote_settles_a_claim_with_a_dead_link_too():
    """Best-first. A claim whose evidence is one live quote and two dead links
    is a claim whose evidence held up; the other reading would make every old
    source look like a refutation."""
    pages = {
        "https://dead.test/a": (None, "could not read the page: timed out"),
        "https://live.test/b": ("... " + QUOTE + " ...", ""),
    }
    real = factcheck.fetch
    factcheck.fetch = lambda url, opener=None: pages[url]
    try:
        result = factcheck.check_claim(
            [
                {"url": "https://dead.test/a", "quote": QUOTE},
                {"url": "https://live.test/b", "quote": QUOTE},
            ]
        )
    finally:
        factcheck.fetch = real
    assert result["verdict"] == "quoted"
    assert len(result["sources"]) == 2


# ── the endpoint ─────────────────────────────────────────────────────────


def test_the_quote_checked_is_the_packs_own(client, monkeypatch):
    """The caller sends an address and nothing else. A check whose input came
    from the caller would prove nothing — and the extension is a caller."""
    seen = {}

    def fetch(url, opener=None):
        seen["url"] = url
        return "a page that happens to contain " + QUOTE, ""

    monkeypatch.setattr(factcheck, "fetch", fetch)
    row = client.post("/api/factcheck", json={"pack_id": "p", "claim_id": "c1"}).json()
    assert row["verdict"] == "quoted"
    assert seen["url"] == "https://example.test/a"
    # Snapshotted, so the row stays readable after the pack is updated.
    assert row["title"] == "Belt due"
    assert row["subject_id"] == "s1"


def test_a_rewritten_page_is_a_signal_and_not_a_retraction(client, monkeypatch):
    _page(monkeypatch, "an entirely different article now")
    row = client.post("/api/factcheck", json={"pack_id": "p", "claim_id": "c1"}).json()
    assert row["verdict"] == "missing"
    assert "rewritten" in row["sources"][0]["detail"]
    # The claim itself is untouched: the engine has no authority to retract
    # one, and this is not a way to give it one.
    store = connect(client.app.state.settings.store_path)
    assert store.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 1
    store.close()


def test_an_unreachable_source_says_so_rather_than_failing(client, monkeypatch):
    """A site that is down, or that would rather not be read by an app, is not
    an error in this app — and a 500 would look like one."""
    monkeypatch.setattr(
        factcheck, "fetch", lambda url, opener=None: (None, "the site answered 403")
    )
    response = client.post("/api/factcheck", json={"pack_id": "p", "claim_id": "c1"})
    assert response.status_code == 200
    assert response.json()["verdict"] == "unreachable"
    assert "403" in response.json()["detail"]


def test_pressing_it_twice_replaces_rather_than_accumulates(client, monkeypatch):
    _page(monkeypatch, "nothing like it")
    client.post("/api/factcheck", json={"pack_id": "p", "claim_id": "c1"})
    _page(monkeypatch, QUOTE)
    client.post("/api/factcheck", json={"pack_id": "p", "claim_id": "c1"})
    payload = client.get("/api/factcheck").json()
    assert len(payload["items"]) == 1
    assert payload["counts"] == {"quoted": 1}


def test_a_claim_the_store_does_not_carry_is_a_stale_link(client):
    """A pack updated or removed under a page left open — 404, not 500."""
    assert (
        client.post("/api/factcheck", json={"pack_id": "p", "claim_id": "gone"}).status_code
        == 404
    )


def test_the_whole_screens_verdicts_come_back_in_one_request(client, monkeypatch):
    """A result page shows forty claims. Forty requests to say "not checked
    yet" is why this is a list and not a lookup per card."""
    _page(monkeypatch, QUOTE)
    client.post("/api/factcheck", json={"pack_id": "p", "claim_id": "c1"})
    payload = client.get("/api/factcheck").json()
    assert payload["items"][0]["claim_id"] == "c1"
    assert payload["items"][0]["sources"][0]["url"] == "https://example.test/a"


def test_an_unknown_verdict_filter_is_refused(client):
    assert client.get("/api/factcheck?verdict=true").status_code == 422


def test_a_check_lives_in_the_interfaces_file_not_the_engines(client, monkeypatch):
    """The load-bearing one. A dead link must not change a pack's
    `content_digest`, and one reader's fetch failure must not travel to
    everyone who installs the pack next."""
    _page(monkeypatch, QUOTE)
    client.post("/api/factcheck", json={"pack_id": "p", "claim_id": "c1"})
    store = connect(client.app.state.settings.store_path)
    tables = {
        r[0] for r in store.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    store.close()
    assert "fact_checks" not in tables
    app_conn = state.connect(client.app.state.settings.app_state_path)
    assert state.get_fact_check(app_conn, "p", "c1")["verdict"] == "quoted"
    app_conn.close()


# --- the closed vocabulary -------------------------------------------------
#
# Three surfaces put the verdicts into words: this app's report, the browser
# panel, and nothing else. A verdict added here and missed there renders as
# the bare token — "unreadable" as a sentence to a reader who did not write
# it — or worse, as a blank where reassurance used to be. The maps say they
# are held together by this test, so this test has to exist.

ROOT = Path(__file__).resolve().parents[3]
PANEL = ROOT / "extension" / "hover_lite" / "risk_card.js"
REPORT = ROOT / "ui" / "src" / "lib" / "report.ts"


def _keys(text: str, name: str) -> set[str]:
    """The keys of one object literal, by name. Deliberately dumb: a regex
    over a map of four string constants beats a JS parser as a dependency,
    and a rename that breaks the regex fails the test, which is the point."""
    match = re.search(name + r"[^{]*\{(.*?)\}", text, re.S)
    assert match, f"no {name} map in the file — was it renamed?"
    return set(re.findall(r"^\s*(\w+)\s*:", match.group(1), re.M))


def test_the_panel_words_every_verdict_and_invents_none():
    assert _keys(PANEL.read_text(), "FACT_WORD") == set(factcheck.VERDICTS)


def test_the_report_words_and_tones_every_verdict():
    text = REPORT.read_text()
    # Tone as well as wording: an untoned verdict falls back to neutral, so a
    # new "retracted" would arrive looking like a footnote.
    assert _keys(text, "FACT_WORD") == set(factcheck.VERDICTS)
    assert _keys(text, "FACT_TONE") == set(factcheck.VERDICTS)


def test_the_extension_asks_the_app_rather_than_judging_a_page_itself():
    """The panel's button must be a message to this app, not a fetch of its
    own: a content script that read the cited page directly would be doing it
    with the reader's cookies on a domain they never chose to visit."""
    background = (ROOT / "extension" / "background.js").read_text()
    assert "CHECK_FACTS" in background
    assert "/api/factcheck" in background
