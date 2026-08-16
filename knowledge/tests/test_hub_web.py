"""kriko-hub web API — the browser dashboard's data plane (B20 web edition).

Requires fastapi (+ httpx for TestClient), i.e. run under the .venv
(.venv/bin/python -m pytest knowledge/tests/test_hub_web.py). The system
python suite skips these via importorskip.
"""

import tempfile
import time
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from knowledge.hub import web  # noqa: E402


@pytest.fixture
def client():
    return TestClient(web.app)


def test_index_serves_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "kriko-hub" in r.text
    assert "/static/hub.js" in r.text and "/static/style.css" in r.text


def test_static_assets_served(client):
    assert client.get("/static/hub.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200


def test_state_has_catalog_kpis(client):
    d = client.get("/api/state").json()
    cat = d["catalog"]
    assert set(cat) == {"parts", "variants", "fitment", "claims"}
    assert all(isinstance(v, int) and v >= 0 for v in cat.values())
    assert "findings" not in d  # heavy report stays out of the poll path


def test_coverage_endpoint_on_demand_and_cached(client):
    d = client.get("/api/coverage").json()
    assert isinstance(d["findings"], list)
    assert "ts" in d
    again = client.get("/api/coverage").json()
    assert again["ts"] == d["ts"]  # cached within TTL


def test_table_endpoint_reports_row_count(client):
    d = client.get("/api/table/documents").json()
    assert isinstance(d["count"], int)
    assert "head" in d and "body" in d
    assert client.get("/api/table/nope").status_code == 404


def test_served_js_parses_when_node_available(client):
    """Regression guard: the page's JS must stay syntactically valid. The
    2026-08-04 bug: a \\n escape inside the page string became a literal
    newline in the served script, killing every click handler. Skipped when
    node is not installed."""
    node = __import__("shutil").which("node")
    if not node:
        pytest.skip("node not installed")
    js = client.get("/static/hub.js").text
    import subprocess
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(js)
        path = f.name
    r = subprocess.run([node, "--check", path], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_state_snapshot_shape(client):
    s = client.get("/api/state").json()
    for k in ("counts", "spend", "pending", "parts", "documents",
              "catalog", "runs"):
        assert k in s
    assert s["counts"]["documents"] > 0


def test_part_and_doc_routes(client):
    parts = client.get("/api/state").json()["parts"]
    pid = parts[0]["part_id"]
    p = client.get(f"/api/part/{pid}")
    assert p.status_code == 200 and p.json()["part_id"] == pid
    assert client.get("/api/part/nope").status_code == 404
    d = client.get("/api/doc/1")
    assert d.status_code in (200, 404)


def test_table_browser(client):
    r = client.get("/api/table/documents")
    assert r.status_code == 200
    assert "url" in r.json()["head"]
    assert client.get("/api/table/not_a_table").status_code == 404


def test_run_validates_argv(client):
    assert client.post("/api/run", json={"argv": "x"}).status_code == 400
    assert client.post("/api/run", json={"argv": []}).status_code == 400
    assert client.post("/api/run",
                       json={"argv": ["rm", "-rf", "/"]}).status_code == 400


def test_run_report_streams_to_log(tmp_path):
    client = TestClient(web.app)
    db_path = tmp_path / "l.db"
    r = client.post("/api/run", json={"argv": ["report", "--db", str(db_path)]})
    assert r.status_code == 200
    buf = ""
    for _ in range(200):
        lg = client.get("/api/log").json()
        if not lg["running"] and lg["buf"]:
            buf = lg["buf"]
            break
        time.sleep(0.05)
    assert "TOTAL" in buf


def test_stop_idempotent(client):
    r = client.post("/api/stop")
    assert r.status_code == 200
    assert "stopped" in r.json()


# ── Models tab: onboarding state + agent driver (B23) ────────────────────────


def test_models_endpoint_lists_catalogued_cars(client):
    d = client.get("/api/models").json()
    assert isinstance(d["models"], list) and d["models"]
    m = d["models"][0]
    for k in ("model_key", "make", "model", "variants", "variants_draft",
              "rollup"):
        assert k in m
    assert set(m["rollup"]) == {"missing", "zero_claim", "has_claims"}


def test_model_detail_returns_the_work_list(client):
    key = client.get("/api/models").json()["models"][0]["model_key"]
    d = client.get(f"/api/model/{key}").json()
    assert d["model_key"] == key
    assert d["has_variants"] is True
    assert isinstance(d["parts"], list)
    assert all(p["state"] in ("missing", "zero_claim", "has_claims")
               for p in d["parts"])


def test_model_detail_rejects_a_malformed_key(client):
    assert client.get("/api/model/nope").status_code == 400
    assert client.get("/api/model/..%2F..%2Fetc").status_code in (400, 404)


# The onboard endpoint turns a text box into a subprocess. These are the gates.


@pytest.fixture
def spawned(monkeypatch):
    calls = []
    monkeypatch.setattr(web, "_spawn", lambda cmd: calls.append(cmd) or " ".join(cmd))
    return calls


def test_onboard_spawns_the_agent_for_a_valid_model(client, spawned):
    r = client.post("/api/onboard", json={"make": "renault",
                                          "model": "megane_4",
                                          "harness": "opencode"})
    assert r.status_code == 200
    assert len(spawned) == 1
    argv = spawned[0]
    assert Path(argv[0]).name == "opencode"  # resolved to an absolute binary
    assert "kriko_research" in argv
    assert any("renault megane_4" in a for a in argv)


def test_onboard_supports_claude_code(client, spawned):
    r = client.post("/api/onboard", json={"make": "renault", "model": "clio_5",
                                          "harness": "claude"})
    assert r.status_code == 200
    assert Path(spawned[0][0]).name == "claude"


def test_onboard_rejects_shell_metacharacters(client, spawned):
    r = client.post("/api/onboard", json={"make": "renault; rm -rf /",
                                          "model": "clio_5",
                                          "harness": "opencode"})
    assert r.status_code == 400
    assert spawned == []


def test_onboard_rejects_path_traversal(client, spawned):
    r = client.post("/api/onboard", json={"make": "../../etc",
                                          "model": "passwd",
                                          "harness": "opencode"})
    assert r.status_code == 400
    assert spawned == []


def test_onboard_rejects_an_unknown_harness(client, spawned):
    r = client.post("/api/onboard", json={"make": "renault", "model": "clio_5",
                                          "harness": "bash"})
    assert r.status_code == 400
    assert spawned == []


def test_onboard_rejects_empty_fields(client, spawned):
    assert client.post("/api/onboard", json={"make": "", "model": "clio_5",
                                             "harness": "opencode"}
                       ).status_code == 400
    assert spawned == []


# Real-time visibility: the agent writes through MCP, so every action it takes
# leaves a ledger row. The feed reads those, not the harness's stdout.


def test_activity_feed_returns_recent_ledger_writes(client):
    d = client.get("/api/activity").json()
    assert isinstance(d["events"], list)
    for e in d["events"]:
        assert e["kind"] in ("document", "evidence")
        assert "at" in e and "label" in e


def test_activity_feed_marks_agent_authored_evidence(client):
    d = client.get("/api/activity?limit=200").json()
    ev = [e for e in d["events"] if e["kind"] == "evidence"]
    if ev:
        assert all("by_agent" in e for e in ev)


def test_activity_feed_limit_is_bounded(client):
    d = client.get("/api/activity?limit=100000").json()
    assert len(d["events"]) <= web.MAX_ACTIVITY


def test_opencode_agent_is_launchable_as_primary():
    """Regression guard, 2026-08-16: `opencode run --agent kriko_research`
    silently FELL BACK to the default `build` agent when the file declared
    `mode: subagent` — so the hub's Onboard button launched an unrestricted
    agent (bash+edit allowed) instead of the sandboxed researcher. Only
    `primary` or `all` is directly launchable."""
    fm = (Path(__file__).resolve().parents[2] / ".opencode" / "agents"
          / "kriko_research.md").read_text().split("---")[1]
    mode = [l.split(":", 1)[1].strip() for l in fm.splitlines()
            if l.startswith("mode:")]
    assert mode and mode[0] in ("primary", "all"), (
        f"mode={mode} — 'subagent' cannot be launched by `opencode run --agent`")


# ── Top-down picker: demand → model → generation (B23) ───────────────────────


def test_demand_endpoint_groups_by_make(client):
    d = client.get("/api/demand").json()
    assert isinstance(d["makes"], list)
    for m in d["makes"]:
        assert "make" in m and isinstance(m["models"], list)
        for mod in m["models"]:
            assert {"model", "slug", "hits", "reason"} <= set(mod)


def test_demand_surfaces_not_onboarded_cars_first(client):
    """The picker exists to onboard cars buyers hit that we don't cover."""
    d = client.get("/api/demand").json()
    reasons = [mod["reason"] for m in d["makes"] for mod in m["models"]]
    assert "not_onboarded" in reasons


def test_generations_endpoint_reports_unresearched(client):
    d = client.get("/api/generations/audi/definitely_not_a_car").json()
    assert d["researched"] is False
    assert d["generations"] == []


def test_generations_endpoint_rejects_a_malformed_make(client):
    assert client.get("/api/generations/..%2Fetc/q2").status_code in (400, 404)


def test_research_generations_spawns_the_agent(client, spawned):
    r = client.post("/api/research-generations",
                    json={"make": "audi", "model": "q2", "harness": "opencode"})
    assert r.status_code == 200
    assert len(spawned) == 1
    assert any("generations" in a and "audi q2" in a for a in spawned[0])


def test_research_generations_applies_the_same_gates(client, spawned):
    assert client.post("/api/research-generations",
                       json={"make": "audi; rm -rf /", "model": "q2",
                             "harness": "opencode"}).status_code == 400
    assert client.post("/api/research-generations",
                       json={"make": "audi", "model": "q2",
                             "harness": "bash"}).status_code == 400
    assert spawned == []


def test_onboard_appends_the_generation_to_the_model_key(client, spawned):
    r = client.post("/api/onboard", json={"make": "audi", "model": "q2",
                                          "generation": 1,
                                          "harness": "opencode"})
    assert r.status_code == 200
    assert r.json()["model_key"] == "audi_q2_1"
    assert any("audi q2_1" in a for a in spawned[0])


def test_onboard_rejects_a_nonsense_generation(client, spawned):
    for bad in (0, -1, "IV", 99):
        assert client.post("/api/onboard",
                           json={"make": "audi", "model": "q2",
                                 "generation": bad,
                                 "harness": "opencode"}).status_code == 400
    assert spawned == []


def test_onboard_without_a_generation_still_works(client, spawned):
    """Already-keyed models (megane_4) carry their generation in the slug."""
    r = client.post("/api/onboard", json={"make": "renault",
                                          "model": "megane_4",
                                          "harness": "opencode"})
    assert r.status_code == 200
    assert r.json()["model_key"] == "renault_megane_4"


# ── Harness + model selection, command preview (B23) ─────────────────────────


def test_harnesses_endpoint_lists_installed_harnesses(client):
    d = client.get("/api/harnesses").json()
    names = {h["name"] for h in d["harnesses"]}
    assert {"opencode", "claude"} <= names
    for h in d["harnesses"]:
        assert isinstance(h["available"], bool)
        assert isinstance(h["models"], list)


def test_harness_models_are_discovered_not_hardcoded(client):
    """opencode enumerates its own models; we never ship a list of them."""
    d = client.get("/api/harnesses").json()
    oc = next(h for h in d["harnesses"] if h["name"] == "opencode")
    if oc["available"]:
        assert oc["models"], "opencode reported no models"


def test_agent_preview_returns_the_exact_argv_without_spawning(client, spawned):
    r = client.post("/api/agent-preview",
                    json={"task": "generations", "make": "audi", "model": "q2",
                          "harness": "opencode"})
    assert r.status_code == 200
    d = r.json()
    assert any("find generations for audi q2" in a for a in d["argv"])
    assert isinstance(d["display"], str) and d["display"]
    assert spawned == []  # preview must never launch anything


def test_agent_preview_includes_the_chosen_model(client, spawned):
    d = client.post("/api/agent-preview",
                    json={"task": "onboard", "make": "audi", "model": "q2",
                          "generation": 1, "harness": "opencode",
                          "llm_model": "opencode-go/gpt-5.6-luna"}).json()
    assert "-m" in d["argv"]
    assert "opencode-go/gpt-5.6-luna" in d["argv"]
    assert any("onboard audi q2_1" in a for a in d["argv"])


def test_agent_preview_rejects_an_unknown_task(client):
    assert client.post("/api/agent-preview",
                       json={"task": "rm -rf /", "make": "audi", "model": "q2",
                             "harness": "opencode"}).status_code == 400


def test_agent_preview_applies_the_same_input_gates(client):
    assert client.post("/api/agent-preview",
                       json={"task": "onboard", "make": "audi; rm -rf /",
                             "model": "q2", "harness": "opencode"}
                       ).status_code == 400


def test_a_bogus_model_string_is_refused(client, spawned):
    """llm_model reaches argv — it gets the same treatment as make/model."""
    assert client.post("/api/onboard",
                       json={"make": "audi", "model": "q2", "harness": "opencode",
                             "llm_model": "x; rm -rf /"}).status_code == 400
    assert spawned == []


def test_onboard_passes_the_model_through_to_the_agent(client, spawned):
    r = client.post("/api/onboard",
                    json={"make": "audi", "model": "q2", "harness": "opencode",
                          "llm_model": "opencode-go/kimi-k3"})
    assert r.status_code == 200
    assert "opencode-go/kimi-k3" in spawned[0]


def test_preview_and_run_produce_the_same_argv(client, spawned):
    """The preview must be the command, not a second implementation of it."""
    body = {"task": "onboard", "make": "renault", "model": "clio_5",
            "generation": 5, "harness": "opencode",
            "llm_model": "opencode-go/glm-5.3"}
    preview = client.post("/api/agent-preview", json=body).json()["argv"]
    client.post("/api/onboard", json={k: v for k, v in body.items()
                                      if k != "task"})
    assert spawned[0] == preview


# ── Paid-model guard (B23) ───────────────────────────────────────────────────
#
# .env carries provider API keys, and the hub passes .env to the harness — so
# `opencode models` reports every pay-per-token provider those keys unlock
# (406 models, vs 26 on the subscription plan alone). Offering those unlabelled
# would let one dropdown pick silently spend API credits, defeating the whole
# $0 premise of the agent path.


def test_paid_providers_are_derived_from_env_api_keys(tmp_path):
    env = {"DEEPSEEK_API_KEY": "x", "OPENROUTER_API_KEY": "y",
           "MISTRAL_AGENT_API_KEY": "z", "PATH": "/usr/bin"}
    paid = web._paid_providers(env)
    assert {"deepseek", "openrouter", "mistral"} <= paid
    assert "path" not in paid


def test_a_model_from_an_api_key_provider_is_marked_paid():
    paid = {"deepseek", "openrouter"}
    assert web._is_paid("deepseek/deepseek-v4-flash", paid)
    assert web._is_paid("openrouter/anything", paid)
    assert not web._is_paid("opencode-go/gpt-5.6-luna", paid)
    assert not web._is_paid("opencode/big-pickle", paid)


def test_harnesses_endpoint_splits_free_from_paid(client):
    d = client.get("/api/harnesses").json()
    oc = next(h for h in d["harnesses"] if h["name"] == "opencode")
    if not oc["available"]:
        pytest.skip("opencode not installed")
    assert "models" in oc and "paid_models" in oc
    # the subscription plane must never contain an API-key provider
    paid = web._paid_providers(web._load_env())
    assert not any(web._is_paid(m, paid) for m in oc["models"])
