"""B128 was half-built: `regrounded` (grounded/ungrounded/not_kept, offline,
against the page this install actually kept) existed and was fully tested in
isolation, but nothing called it. `tasks.verify` ran only the live-fetch
check (`factcheck.check_claim`), and no router surfaced a retained document
at all — so a reader had no way to see "here is the page that proved this
quote", and `not_kept` (true of essentially every pack-shipped claim, since
only the acceptance path retains a document) never reached anyone.

These tests are for the wiring: `verify` now reports a `grounding` tally
alongside `verdicts`, kept as its own dict so `not_kept` cannot be read as a
pass, and two routes expose the per-evidence verdict and the document text
itself.
"""

import pytest
from fastapi.testclient import TestClient

from app import findings
from app.web import state
from app.web.app import create_app
from app.web.settings import Settings
from kriko.store.db import connect


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        store_path=tmp_path / "k.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "a.jsonl",
    )


def _seed_with_document(settings, *, quote="the thing fails", page=None):
    conn = connect(settings.store_path)
    conn.execute(
        "INSERT INTO packs (pack_id, name, version, schema_version, built_at,"
        " content_digest, enabled, installed_at)"
        " VALUES ('probe', 'Probe', '1', 1, '2026-09-01', 'd', 1, '2026-09-01')"
    )
    conn.execute(
        "INSERT INTO subjects (subject_id, pack_id, kind, label)"
        " VALUES ('s1', 'probe', 'product', 'Thing')"
    )
    conn.execute(
        "INSERT INTO claims (claim_id, pack_id, subject_id, kind, domain,"
        " severity, author_confidence, created_at)"
        " VALUES ('c1', 'probe', 's1', 'known_issue', 'engine', 'high', 0.6,"
        " datetime('now'))"
    )
    conn.execute(
        "INSERT INTO claim_text VALUES ('c1', 'probe', 'en', 'A known thing',"
        " 'body', 'advice')"
    )
    conn.execute(
        "INSERT INTO sources (source_id, pack_id, url, domain, site_or_channel,"
        " title, lang, source_type, published_at, retrieved_at)"
        " VALUES ('src1', 'probe', 'https://example.test/t', 'example.test',"
        " '', '', 'en', 'page', '', '2026-09-01')"
    )
    conn.execute(
        "INSERT INTO evidence (evidence_id, pack_id, claim_id, source_id,"
        " quote, locator, stance, independent)"
        " VALUES ('e1', 'probe', 'c1', 'src1', ?, '', 'supports', 1)",
        (quote,),
    )
    conn.commit()
    conn.close()
    if page is not None:
        app_conn = state.connect(settings.app_state_path)
        state.retain_documents(
            app_conn,
            [{"source_id": "src1", "pack_id": "probe",
              "url": "https://example.test/t", "text": page}],
        )
        app_conn.close()


class _Progress:
    def log(self, line: str) -> None:
        pass

    def set(self, progress: float, message: str = "") -> None:
        pass

    def check(self) -> None:
        pass


def test_verify_tallies_grounding_separately_from_the_live_check(
    settings, monkeypatch
):
    from app import factcheck
    from app.web import tasks

    _seed_with_document(settings, page="the thing fails, widely reported")
    monkeypatch.setattr(
        factcheck, "check_claim",
        lambda sources, **kw: {"verdict": factcheck.QUOTED, "detail": "",
                               "sources": list(sources)},
    )
    result = tasks.verify(settings, {"pack_id": "probe"}, _Progress())
    assert result["grounding"] == {"grounded": 1}
    assert result["claims"][0]["grounding"][0]["verdict"] == "grounded"


def test_a_claim_with_no_retained_document_reports_not_kept_not_a_pass(
    settings, monkeypatch
):
    """The claim ships with a pack — nothing was ever fetched through the
    acceptance path — so the live check may say `quoted` while grounding must
    say `not_kept`, and the two tallies must not collapse into one."""
    from app import factcheck
    from app.web import tasks

    _seed_with_document(settings, page=None)
    monkeypatch.setattr(
        factcheck, "check_claim",
        lambda sources, **kw: {"verdict": factcheck.QUOTED, "detail": "",
                               "sources": list(sources)},
    )
    result = tasks.verify(settings, {"pack_id": "probe"}, _Progress())
    assert result["verdicts"] == {factcheck.QUOTED: 1}
    assert result["grounding"] == {"not_kept": 1}
    assert "not_kept" not in result["verdicts"]


def test_a_page_that_changed_reports_ungrounded_even_if_the_live_check_lags(
    settings, monkeypatch
):
    from app import factcheck
    from app.web import tasks

    _seed_with_document(settings, page="this page has been replaced entirely")
    monkeypatch.setattr(
        factcheck, "check_claim",
        lambda sources, **kw: {"verdict": factcheck.QUOTED, "detail": "",
                               "sources": list(sources)},
    )
    result = tasks.verify(settings, {"pack_id": "probe"}, _Progress())
    assert result["grounding"] == {"ungrounded": 1}


def test_the_grounding_router_reports_per_evidence(settings):
    _seed_with_document(settings, page="the thing fails, widely reported")
    client = TestClient(create_app(settings))
    response = client.get(
        "/api/factcheck/grounding", params={"pack_id": "probe", "claim_id": "c1"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["evidence"][0]["verdict"] == "grounded"
    assert body["not_kept"] == 0


def test_the_grounding_router_404s_for_an_unknown_claim(settings):
    _seed_with_document(settings, page="x")
    client = TestClient(create_app(settings))
    response = client.get(
        "/api/factcheck/grounding",
        params={"pack_id": "probe", "claim_id": "no-such-claim"})
    assert response.status_code == 404


def test_the_document_router_serves_the_page_that_proved_the_quote(settings):
    _seed_with_document(settings, page="the thing fails, widely reported")
    client = TestClient(create_app(settings))
    response = client.get("/api/factcheck/document", params={"source_id": "src1"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert "the thing fails" in body["text"]
    assert body["url"] == "https://example.test/t"


def test_the_document_router_404s_as_not_kept_when_nothing_was_retained(
    settings
):
    _seed_with_document(settings, page=None)
    client = TestClient(create_app(settings))
    response = client.get("/api/factcheck/document", params={"source_id": "src1"})
    assert response.status_code == 404
    assert "not_kept" in response.text
