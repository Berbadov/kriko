"""A reader reports a failed run or sends a suggestion.

Kriko composes the text, redacted, and sends nothing: the reader copies it,
saves it or opens a prefilled issue and presses Submit themselves.
"""

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app import report
from app.web import state
from app.web.app import create_app
from app.web.jobs import JobRunner
from app.web.settings import EXTENSION_PORT, Settings

KEY = "sk-live-0123456789abcdefABCDEF"


@pytest.fixture
def settings(tmp_path):
    return Settings(
        store_path=tmp_path / "knowledge.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "analyses.jsonl",
        packs_dir=tmp_path / "packs",
        issues_url="https://issues.example.test/new",
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client


def failed_job(settings):
    def handler(settings_, params, progress):
        progress.log('searched "model 300 problems"')
        progress.log(f"opened {Path.home()}/notes and key {KEY}")
        raise TimeoutError("Mistral did not finish within 30s")

    runner = JobRunner(settings, {"quick_look": handler})
    conn = state.connect(settings.app_state_path)
    try:
        job_id = state.create_job(conn, "quick_look", {"product": "Model 300"})
        runner._run(job_id, "quick_look", {"product": "Model 300"})
        return job_id
    finally:
        runner.shutdown(wait=True)
        conn.close()


def draft(client, **body):
    return client.post("/api/report/draft", json=body)


def test_a_failed_run_is_reported_with_its_log_and_no_secret(client, settings):
    job_id = failed_job(settings)
    made = draft(client, kind="error", job_id=job_id, note="Mistral timed out on a quick look").json()

    assert made["title"] == "[problem] Mistral timed out on a quick look"
    for wanted in ("Mistral timed out on a quick look", "quick_look (failed)",
                   "did not finish within 30s", "Kriko ", "agents found:"):
        assert wanted in made["text"]
    assert KEY not in made["text"] and str(Path.home()) not in made["text"]


def test_the_link_opens_a_prefilled_issue_that_fits_in_a_link(client, settings, monkeypatch):
    monkeypatch.setattr(report, "ISSUE_BODY_CHARS", 1000)
    job_id = failed_job(settings)
    made = draft(client, kind="error", job_id=job_id, note="x " * 2000).json()
    link = urlparse(made["url"])
    asked = parse_qs(link.query)

    assert f"{link.scheme}://{link.netloc}{link.path}" == "https://issues.example.test/new"
    assert asked["title"] == [made["title"]]
    assert len(asked["body"][0]) <= 1000 and "full report is on your clipboard" in asked["body"][0]
    assert len(made["text"]) > len(asked["body"][0])


def test_a_suggestion_carries_the_words_and_the_machine_but_no_log(client, settings):
    failed_job(settings)
    made = draft(client, kind="suggestion", note="Let me pin an agent per catalog").json()

    assert made["title"] == "[suggestion] Let me pin an agent per catalog"
    assert "Kriko " in made["text"] and "## Log" not in made["text"]


def test_a_job_that_does_not_exist_is_a_404_and_the_extension_is_refused(client, settings):
    assert draft(client, kind="error", job_id="nope").status_code == 404
    assert draft(client, kind="bogus").status_code == 422

    with TestClient(create_app(settings), base_url=f"http://127.0.0.1:{EXTENSION_PORT}") as extension:
        extension.app.state.settings = settings
        refused = extension.post("/api/report/draft", json={"kind": "suggestion", "note": "hi"},
                                 headers={"origin": "chrome-extension://abc"})
        assert refused.status_code == 403
