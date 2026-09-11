"""The extension's research door — Phase 6 of the knowledge-building design.

`docs/superpowers/specs/2026-09-09-knowledge-building-design.md` §3 ("the
extension door") sets two rules for the panel's "research this gap" prompt:

  1. It appears only when a subject exists and has no claims — never on
     `NOT_MATCHED`, because a page nothing adapted has no subject to research.
  2. It names the cost before it spends: free on the agent plane, an actual
     number on the api plane.

There is no JS test runner in this repository (see `extension/tests/` for the
node:test suite that exercises the panel directly), so — matching the existing
pattern in `test_factcheck.py::test_the_panel_words_every_verdict_and_invents_none`
— these tests read the extension's own source and assert on it, plus a small
FastAPI test of the one new endpoint the panel needed to ask.
"""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.web.app import create_app
from app.web.settings import Settings

ROOT = Path(__file__).resolve().parents[3]
PANEL = ROOT / "extension" / "hover_lite" / "hover_lite.js"
WORKER = ROOT / "extension" / "background.js"


def _client(tmp_path, **over):
    return TestClient(
        create_app(
            Settings(
                store_path=tmp_path / "knowledge.sqlite",
                app_state_path=tmp_path / "app.sqlite",
                analysis_log_path=tmp_path / "analyses.jsonl",
                **over,
            )
        )
    )


# ── rule 1: guarded on NOT_MATCHED ─────────────────────────────────────────


def test_the_research_prompt_is_built_only_from_resolved_subjects_with_no_claims():
    """The gap card's whole existence is gated on this filter.

    `NOT_MATCHED` never needs a special case here because the backend already
    makes it unreachable: `kriko.lookup.lookup` returns an empty `subjects`
    tuple exactly when nothing matched (`src/kriko/lookup/__init__.py`), and
    `analyze.py::_resolved` only ever populates `subjects` from resolved
    `subject_ids`. So the one thing this test has to hold is that `renderGaps`
    still reads its list from `state.result.subjects` filtered to `!s.claims`
    — anything else (a hardcoded fallback, a check keyed on `coverage`
    instead) would be a second, independent path that could show the button
    with no subject behind it.
    """
    text = PANEL.read_text()
    match = re.search(r"function renderGaps\(\)\s*\{(.*?)\n  \}", text, re.S)
    assert match, "renderGaps() is gone or was renamed"
    body = match.group(1)
    assert re.search(
        r"state\.result\.subjects\s*\|\|\s*\[\]\)\.filter\(\(s\)\s*=>\s*!s\.claims\)",
        body,
    ), "renderGaps no longer derives its list from subjects with no claims"


def test_the_worker_never_offers_research_with_no_subject_id():
    """`RESEARCH_SUBJECT` refuses with nothing to research, on the worker's
    own side too — a defence in depth for the same rule, since the panel is
    not the only thing that could send this message."""
    text = WORKER.read_text()
    match = re.search(
        r'request\.type === "RESEARCH_SUBJECT"\)\s*\{(.*?)\n  \}', text, re.S
    )
    assert match, "the RESEARCH_SUBJECT handler is gone or was renamed"
    body = match.group(1)
    assert "if (!subject_id)" in body
    assert "Missing subject" in body


# ── rule 2: cost named before spending ─────────────────────────────────────


def test_the_panel_names_the_cost_for_both_planes_before_the_button_is_clicked():
    text = PANEL.read_text()
    match = re.search(r"function costLine\(\)\s*\{(.*?)\n  \}", text, re.S)
    assert match, "costLine() is gone or was renamed"
    body = match.group(1)
    assert "Costs money" in body, "the api plane's sentence is missing"
    assert "Costs nothing" in body, "the agent plane's sentence is missing"
    # It has to actually reach the card, not just exist as dead code.
    assert re.search(r'lite-gap-cost.*costLine\(\)|costLine\(\).*lite-gap-cost', text) or (
        "const cost = costLine();" in text and "lite-gap-cost" in text
    )


def test_the_panel_asks_the_app_which_plane_is_configured_before_naming_a_cost():
    """The cost line must come from the app's own answer, not a guess baked
    into the extension — a guess is exactly the failure mode the design calls
    out (a panel that quietly bills someone)."""
    text = PANEL.read_text()
    assert "RESEARCH_PLANE" in text
    assert "requestResearchPlane" in text

    worker = WORKER.read_text()
    assert '"RESEARCH_PLANE"' in worker
    assert "/api/extension/research-plane" in worker


def test_the_research_plane_endpoint_reports_free_by_default(tmp_path, monkeypatch):
    from app.providers import harness as harness_mod

    monkeypatch.setattr(harness_mod, "available", lambda: [])
    client = _client(tmp_path)
    body = client.get("/api/extension/research-plane").json()
    assert body["backend"] == "agent"
    assert body["cost_basis"] == "subscription"
    assert body["budget_usd"] == 0.0


def test_the_research_plane_endpoint_prefers_harness_when_one_is_on_path(
    tmp_path, monkeypatch
):
    from app.providers import harness as harness_mod

    monkeypatch.setattr(harness_mod, "available", lambda: [harness_mod.KNOWN[0]])
    client = _client(tmp_path)
    body = client.get("/api/extension/research-plane").json()
    assert body["backend"] == "harness"
    assert body["cost_basis"] == "subscription"
    assert body["budget_usd"] == 0.0


def test_the_research_plane_endpoint_reports_a_capped_spend_once_both_keys_exist(
    tmp_path,
):
    (tmp_path / "app.sqlite").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "env").write_text(
        "EXA_API_KEY=FIXTURE-SEARCH-KEY\nOPENAI_API_KEY=FIXTURE-LLM-KEY\n"
    )
    client = _client(tmp_path)
    body = client.get("/api/extension/research-plane").json()
    assert body["backend"] == "api"
    assert body["cost_basis"] == "per_token"
    assert body["budget_usd"] > 0


def test_the_research_plane_endpoint_never_returns_a_key(tmp_path):
    """Same discipline `GET /api/keys` holds itself to: the fixture key string
    must not appear anywhere in the response, including if a future edit adds
    an error path that echoes something back."""
    (tmp_path / "app.sqlite").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "env").write_text(
        "EXA_API_KEY=FIXTURE-DO-NOT-LEAK-1234\n"
        "OPENAI_API_KEY=FIXTURE-DO-NOT-LEAK-5678\n"
    )
    client = _client(tmp_path)
    response = client.get("/api/extension/research-plane")
    assert "FIXTURE-DO-NOT-LEAK" not in response.text


# ── the click posts to /api/research and does not navigate away ───────────


def test_clicking_research_posts_to_api_research_and_does_not_raise_the_app():
    """`RESEARCH_SUBJECT` used to call `openInApp("jobs")` on success — the
    reader's click opened a different window. Phase 6 replaced that with
    inline polling (`JOB_STATUS`), so the handler must post the job and stop:
    raising the app here would be a navigation the design explicitly rules
    out ("it does not navigate away")."""
    text = WORKER.read_text()
    match = re.search(
        r'request\.type === "RESEARCH_SUBJECT"\)\s*\{(.*?)\n  \}', text, re.S
    )
    assert match
    body = match.group(1)
    assert '"/api/research"' in body
    assert "openInApp" not in body, (
        "RESEARCH_SUBJECT must not raise the app window — progress belongs "
        "in the panel (JOB_STATUS), per the design's 'does not navigate away'"
    )


def test_the_panel_polls_job_status_for_inline_progress():
    text = PANEL.read_text()
    assert "JOB_STATUS" in text
    assert "pollResearchJob" in text
    worker = WORKER.read_text()
    match = re.search(r'request\.type === "JOB_STATUS"\)\s*\{(.*?)\n  \}', worker, re.S)
    assert match, "the JOB_STATUS handler is gone or was renamed"
    assert "/api/jobs/" in match.group(1)
