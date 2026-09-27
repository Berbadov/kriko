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

import json
import re
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
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
    text = PANEL.read_text(encoding="utf-8")
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
    text = WORKER.read_text(encoding="utf-8")
    match = re.search(
        r'request\.type === "RESEARCH_SUBJECT"\)\s*\{(.*?)\n  \}', text, re.S
    )
    assert match, "the RESEARCH_SUBJECT handler is gone or was renamed"
    body = match.group(1)
    assert "if (!subject_id)" in body
    assert "Missing subject" in body


# ── rule 2: cost named before spending ─────────────────────────────────────


def test_the_panel_names_the_cost_for_both_planes_before_the_button_is_clicked():
    text = PANEL.read_text(encoding="utf-8")
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
    text = PANEL.read_text(encoding="utf-8")
    assert "RESEARCH_PLANE" in text
    assert "requestResearchPlane" in text

    worker = WORKER.read_text(encoding="utf-8")
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
    , encoding="utf-8")
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
    , encoding="utf-8")
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
    text = WORKER.read_text(encoding="utf-8")
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
    text = PANEL.read_text(encoding="utf-8")
    assert "JOB_STATUS" in text
    assert "pollResearchJob" in text
    worker = WORKER.read_text(encoding="utf-8")
    match = re.search(r'request\.type === "JOB_STATUS"\)\s*\{(.*?)\n  \}', worker, re.S)
    assert match, "the JOB_STATUS handler is gone or was renamed"
    assert "/api/jobs/" in match.group(1)


@pytest.fixture
def research_client(tmp_path, monkeypatch):
    from app import keys
    from kriko.store.db import connect

    monkeypatch.setattr(keys, "ready", lambda path: True)
    conn = connect(tmp_path / "knowledge.sqlite")
    conn.execute(
        "INSERT INTO packs (pack_id, name, version, schema_version, built_at,"
        " content_digest, enabled, installed_at)"
        " VALUES ('probe', 'Probe', '1', 1, '2026-09-17', 'd', 1, '2026-09-17')"
    )
    conn.execute(
        "INSERT INTO subjects (subject_id, pack_id, kind, label)"
        " VALUES ('one', 'probe', 'product', 'Widget One')"
    )
    conn.commit()
    conn.close()
    client = _client(tmp_path)
    try:
        yield client
    finally:
        client.app.state.jobs.shutdown(wait=True)


@pytest.mark.parametrize("identity", [{"q": "Widget One"}, {"subject_id": "one"}])
@pytest.mark.parametrize("cap,expected", [(None, 0.20), (0.05, 0.05), (100, 0.20)])
def test_post_research_plane_contract(research_client, identity, cap, expected):
    from app.web.deps import get_jobs

    calls = []

    def submit(kind, params):
        calls.append((kind, params))
        return "job-probe"

    research_client.app.dependency_overrides[get_jobs] = lambda: SimpleNamespace(submit=submit)
    body = {**identity, "model": "selected-model", "search": "selected-search"}
    if cap is not None:
        body["cap"] = cap
    response = research_client.post("/api/extension/research-plane", json=body)
    assert response.status_code == 200
    assert response.json() == {
        "job_id": "job-probe", "kind": "research", "subject_id": "one",
        "pack_id": "probe", "backend": "api", "cost_basis": "per_token",
        "budget_usd": expected,
    }
    assert calls == [("research", {
        "subject_id": "one", "pack_id": "probe", "backend": "api",
        "model": "selected-model", "search": "selected-search",
        "budget_usd": expected,
    })]


@pytest.mark.parametrize("body", [
    {}, {"q": " "}, {"subject_id": " "},
    {"q": "Widget", "subject_id": "one"},
    {"subject_id": "one", "cap": 0},
    {"subject_id": "one", "cap": -1},
    {"subject_id": "one", "cap": "NaN"},
    {"subject_id": "one", "cap": "Infinity"},
])
def test_post_research_plane_rejects_invalid_input(research_client, body):
    assert research_client.post("/api/extension/research-plane", json=body).status_code == 422
    assert research_client.get("/api/jobs").json()["items"] == []


@pytest.mark.parametrize("identity", [{"q": "Absent"}, {"subject_id": "absent"}])
def test_post_research_plane_missing_product(research_client, identity):
    assert research_client.post("/api/extension/research-plane", json=identity).status_code == 404
    assert research_client.get("/api/jobs").json()["items"] == []


@pytest.mark.parametrize("allow_draft", [False, True])
def test_post_research_plane_does_not_guess_between_variants(research_client, allow_draft):
    from kriko.store.db import connect

    conn = connect(research_client.app.state.settings.store_path)
    conn.execute(
        "INSERT INTO subjects (subject_id, pack_id, kind, label)"
        " VALUES ('two', 'probe', 'product', 'Widget Two')"
    )
    conn.commit()
    conn.close()
    response = research_client.post("/api/extension/research-plane", json={
        "q": "Widget", "allow_draft": allow_draft,
    })
    assert response.status_code == 409
    assert {one["subject_id"] for one in response.json()["detail"]["items"]} == {"one", "two"}
    assert research_client.get("/api/jobs").json()["items"] == []


@pytest.mark.parametrize("available,backend", [(False, "agent"), (True, "harness")])
def test_post_research_plane_uses_the_advertised_free_plane(
    research_client, monkeypatch, available, backend,
):
    from app import keys
    from app.providers import harness
    from app.web.deps import get_jobs

    monkeypatch.setattr(keys, "ready", lambda path: False)
    monkeypatch.setattr(harness, "available", lambda: available)
    calls = []

    def submit(kind, params):
        calls.append(params)
        return "free-job"

    research_client.app.dependency_overrides[get_jobs] = lambda: SimpleNamespace(submit=submit)
    advertised = research_client.get("/api/extension/research-plane").json()
    response = research_client.post("/api/extension/research-plane", json={
        "subject_id": "one", "cap": 100, "backend": "api", "budget_usd": 100,
    })
    assert response.status_code == 200
    assert response.json()["backend"] == advertised["backend"] == backend
    assert response.json()["budget_usd"] == advertised["budget_usd"] == 0
    assert calls[0]["budget_usd"] == 0
    assert calls[0]["backend"] == backend


def test_post_research_plane_excludes_disabled_packs(research_client):
    from kriko.store.db import connect

    conn = connect(research_client.app.state.settings.store_path)
    conn.execute("UPDATE packs SET enabled = 0")
    conn.commit()
    conn.close()
    for identity in ({"q": "Widget One"}, {"subject_id": "one"}):
        response = research_client.post("/api/extension/research-plane", json=identity)
        assert response.status_code == 404
    assert research_client.get("/api/jobs").json()["items"] == []


def _wait_research_job(client, job_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        row = client.get(f"/api/jobs/{job_id}").json()
        if row["done"]:
            return row
        time.sleep(0.02)
    pytest.fail(f"job {job_id} did not finish")


def test_post_research_plane_cap_reaches_the_paid_pipeline(research_client, monkeypatch):
    from app.web import tasks
    from kriko.research import ApiResearcher, ResearchTask

    calls = []
    budgets = []

    def plan(*args, **kwargs):
        budgets.append(kwargs["budget_usd"])
        return ResearchTask(
            subject_id="one", subject_label="Widget One", subject_kind="product",
            pack_id="probe", queries=("first", "second", "third"), **kwargs,
        )

    researcher = ApiResearcher(
        lambda query, limit: calls.append(query) or [], lambda url: "",
        lambda prompt: "[]", price_per_call=0.10,
    )
    monkeypatch.setattr(tasks, "_researcher", lambda params: researcher)
    monkeypatch.setattr(tasks, "plan_task", plan)
    response = research_client.post("/api/extension/research-plane", json={
        "subject_id": "one", "cap": 100,
    })
    row = _wait_research_job(research_client, response.json()["job_id"])
    assert budgets == [0.20]
    assert calls == ["first", "second"]
    assert "BudgetExceeded" in row["message"]
    runs = research_client.get("/api/research-runs").json()["runs"]
    assert runs[0]["outcome"] == "budget"


@pytest.mark.parametrize("identity", [{"q": "Widget One"}, {"subject_id": "one"}])
def test_post_research_plane_cancel_after_start_keeps_gathered_work(
    research_client, monkeypatch, identity,
):
    from app.web import tasks
    from kriko.research import ApiResearcher, ResearchTask

    started = threading.Event()
    release = threading.Event()
    extracted = []

    def fetch(url):
        started.set()
        assert release.wait(10)
        return "Retained evidence from the first source."

    researcher = ApiResearcher(
        lambda query, limit: [{"url": "https://example.test/source"}], fetch,
        lambda prompt: extracted.append(prompt) or "[]",
    )
    monkeypatch.setattr(tasks, "_researcher", lambda params: researcher)
    monkeypatch.setattr(tasks, "plan_task", lambda *args, **kwargs: ResearchTask(
        subject_id="one", subject_label="Widget One", subject_kind="product",
        pack_id="probe", queries=("first",), **kwargs,
    ))
    try:
        response = research_client.post("/api/extension/research-plane", json=identity)
        assert response.status_code == 200
        job_id = response.json()["job_id"]
        assert started.wait(10)
        assert research_client.get(f"/api/jobs/{job_id}").json()["state"] == "running"
        stopped = research_client.post(f"/api/jobs/{job_id}/cancel")
        assert stopped.json() == {"job_id": job_id, "state": "cancelling"}
    finally:
        release.set()
    row = _wait_research_job(research_client, job_id)
    assert row["state"] == "cancelled"
    assert row["result"]["partial"] is True
    assert row["result"]["retained_documents"][0]["text"] == "Retained evidence from the first source."
    assert extracted == []
    runs = research_client.get("/api/research-runs").json()["runs"]
    assert runs[0]["outcome"] == "cancelled"


@pytest.mark.parametrize("allow_draft,expected", [(False, 404), (True, 503)])
def test_unknown_product_never_falls_back_to_paid_research(
    research_client, monkeypatch, allow_draft, expected,
):
    from app.providers import harness

    monkeypatch.setattr(harness, "available", lambda: [])
    response = research_client.post("/api/extension/research-plane", json={
        "q": "Unknown Widget", "allow_draft": allow_draft,
        "model": "paid-model", "search": "paid-search", "cap": 100,
    })
    assert response.status_code == expected
    if allow_draft:
        assert "Install" in response.json()["detail"]
        assert "No API research was started" in response.json()["detail"]
    assert research_client.get("/api/jobs").json()["items"] == []


def test_unknown_subject_id_does_not_author_a_draft(research_client):
    response = research_client.post("/api/extension/research-plane", json={
        "subject_id": "missing", "allow_draft": True,
    })
    assert response.status_code == 404
    assert research_client.get("/api/jobs").json()["items"] == []


@pytest.mark.parametrize("identity", [{"q": "Widget One"}, {"subject_id": "one"}])
def test_draft_opt_in_keeps_known_products_on_research(research_client, identity):
    from app.web.deps import get_jobs

    calls = []

    def submit(kind, params):
        calls.append(kind)
        return "known-job"

    research_client.app.dependency_overrides[get_jobs] = lambda: SimpleNamespace(submit=submit)
    response = research_client.post("/api/extension/research-plane", json={
        **identity, "allow_draft": True,
    })
    assert response.status_code == 200
    assert response.json()["kind"] == "research"
    assert calls == ["research"]


@pytest.mark.parametrize("value", ["false", "true", 1, None])
def test_draft_opt_in_requires_a_boolean(research_client, value):
    response = research_client.post("/api/extension/research-plane", json={
        "q": "Unknown Widget", "allow_draft": value,
    })
    assert response.status_code == 422
    assert research_client.get("/api/jobs").json()["items"] == []


@pytest.mark.parametrize("outcome", ["draft", "refused", "cancelled"])
def test_product_draft_reuses_author_gates_and_cancellation(
    research_client, monkeypatch, outcome,
):
    from app import providers, packdraft
    from app.providers import harness
    from kriko.store.db import connect

    prompts = []
    quick = []
    selected = []
    started = threading.Event()
    release = threading.Event()
    proposal = {
        "pack_id": "probe.widget", "name": "Unknown Widget",
        "languages": ["en"], "markets": ["EU"],
        "identity": {"product": ["series"]},
        "principle": "Surface specific costly failures.",
        "templates": ["{label} failures"],
        "lineup": ["Unknown Widget"],
        "subjects": [{"kind": "product", "label": "Unknown Widget",
                      "identity": {"series": "unknown"}}],
        "claims": [],
    }

    class FakeHarness:
        search_provider = "fixture-harness"

        def ask(self, prompt):
            if prompt.startswith("# Quick look"):
                quick.append(prompt)
                return "```json" + chr(10) + json.dumps({"assumed": "the standard one", "risks": [
                    {"title": "Gear wear", "why": "It wears.", "check": "",
                     "severity": "high", "url": "https://example.org/a",
                     "quote": "the gears wear"},
                    {"title": "Unsourced", "why": "Trust me."},
                ]}) + chr(10) + "```"
            prompts.append(prompt)
            if len(prompts) == 1:
                return json.dumps({
                    "ambiguous": True, "why": "Two variants",
                    "questions": [{"ask": "Which variant?", "default": "standard"}],
                })
            started.set()
            assert release.wait(10)
            self.check_cancelled()
            return json.dumps(proposal) if outcome == "draft" else "not a pack"

    def create(**kwargs):
        selected.append(kwargs)
        return FakeHarness()

    monkeypatch.setattr(harness, "available", lambda: [SimpleNamespace(id="fixture-harness")])
    monkeypatch.setattr(providers, "harness_researcher", create)
    response = research_client.post("/api/extension/research-plane", json={
        "q": " Unknown Widget ", "allow_draft": True,
        "model": "paid-model", "search": "paid-search", "cap": 0.01,
    })
    quick_id = response.json()["job_id"]
    job_id = response.json()["deepen_job_id"]
    try:
        assert response.status_code == 200
        assert response.json() == {
            "job_id": quick_id, "kind": "quick_look", "deepen_job_id": job_id,
            "backend": "harness",
            "harness": "fixture-harness", "cost_basis": "subscription",
            "budget_usd": None,
            "note": "Uses your harness subscription. A quick answer first; the "
                    "deeper research keeps going and installs itself when done.",
        }
        assert started.wait(10)
        # B148: the quick look answers while the deep run is still holding the
        # only main-lane worker — it was never queued behind it.
        looked = _wait_research_job(research_client, quick_id)
        assert looked["state"] == "succeeded", looked["message"]
        assert looked["result"]["deepen_job_id"] == job_id
        assert [r["title"] for r in looked["result"]["risks"]] == ["Gear wear"]
        assert looked["result"]["dropped"] == 1
        assert "Unknown Widget" in quick[0]
        if outcome == "cancelled":
            stopped = research_client.post(f"/api/jobs/{job_id}/cancel")
            assert stopped.json()["state"] == "cancelling"
    finally:
        release.set()
    row = _wait_research_job(research_client, job_id)
    assert selected[0]["preferred"] == "fixture-harness"
    assert "Unknown Widget" in prompts[1]
    assert "Product-only scope" in prompts[1]
    assert "Do not expand to other products" in prompts[1]
    assert "Do not install anything" in prompts[1]
    if outcome == "draft":
        assert row["state"] == "succeeded", row["message"]
        # B148: "yes it should install itslef" — this door installs the draft.
        assert row["result"]["installed"] is True
        assert row["result"]["category"] == "Unknown Widget"
        draft = packdraft.open_draft(research_client.app.state.settings.store_path,
                                     row["result"]["slug"])
        assert "data/subjects.yaml" in draft.files()
    elif outcome == "cancelled":
        assert row["state"] == "cancelled"
        assert row["result"]["partial"] is True
        assert row["result"]["questions"][0]["default"] == "standard"
    else:
        assert row["state"] == "failed"
        assert "did not produce a usable pack" in row["message"]
    conn = connect(research_client.app.state.settings.store_path)
    try:
        packs = sorted(r[0] for r in conn.execute("SELECT pack_id FROM packs"))
        # Installed only when the run produced a pack; a refused or cancelled
        # run leaves the store exactly as it was.
        assert packs == (["probe", row["result"]["pack_id"]] if outcome == "draft"
                         else ["probe"])
        if outcome != "draft":
            assert conn.execute("SELECT COUNT(*) FROM subjects").fetchone()[0] == 1
    finally:
        conn.close()
