"""What was used is kept apart by what it was used on, and a blank is not a zero.

*"The web search API, the LLM API and so on need to be calculated separately,
and for a coding agent the 5 hour and weekly usage left."* Each use is a row
filed under one of four resources; the sums are over rolling windows, only over
the rows that counted, and an agent's own window report is kept as it said it.
"""

import time
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app import limits, usage
from app.providers import harness, websearch
from app.web import state
from app.web.app import create_app
from app.web.settings import Settings


def client(tmp_path):
    return TestClient(create_app(Settings(
        store_path=tmp_path / "knowledge.sqlite", app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "a.jsonl")))


def put(conn, hours_ago, resource, **fields):
    row = {"source": "", "model": "", "calls": 1, "ok": None, "tokens_in": None, "tokens_out": None,
           "tokens": None, "usd": None, **fields}
    conn.executescript(usage._SCHEMA)
    conn.execute(
        "INSERT INTO usage_events (ts, resource, source, model, calls, ok, tokens_in, tokens_out, tokens, usd)"
        " VALUES (?,?,?,?,?,?,?,?,?,?)",
        (time.time() - hours_ago * 3600, resource, row["source"], row["model"], row["calls"], row["ok"],
         row["tokens_in"], row["tokens_out"], row["tokens"], row["usd"]))
    conn.commit()


# ── what an agent says about its windows ─────────────────────────────────


def test_a_rate_limit_event_is_read_in_its_own_words():
    rows = limits.parse({"type": "rate_limit_event", "rate_limit_info": {
        "status": "allowed_warning", "rateLimitType": "five_hour", "utilization": 0.62,
        "resetsAt": 1_800_000_000, "isUsingOverage": False}})
    assert rows == [{"window": "five_hour", "used": 0.62, "status": "allowed_warning",
                     "resets_at": 1_800_000_000.0, "overage": False}]


def test_a_percent_a_millisecond_time_and_an_iso_time_all_read():
    percent = limits.parse({"rate_limit_info": {"rateLimitType": "seven_day", "used_percentage": 41,
                                                "resetsAt": 1_800_000_000_000}})[0]
    assert percent["used"] == 0.41 and percent["resets_at"] == 1_800_000_000.0
    iso = limits.parse({"rate_limit_info": {"rateLimitType": "seven_day", "utilization": 55,
                                            "resets_at": "2027-01-15T08:00:00Z"}})[0]
    assert iso["used"] == 0.55
    assert iso["resets_at"] == datetime(2027, 1, 15, 8, 0, tzinfo=UTC).timestamp()


def test_a_status_with_no_figure_keeps_the_status_and_no_figure():
    row = limits.parse({"rate_limit_info": {"rateLimitType": "five_hour", "status": "allowed"}})[0]
    assert row["used"] is None and row["status"] == "allowed", "nothing is worked out from a status"


def test_an_event_that_says_nothing_returns_nothing():
    assert limits.parse({"type": "rate_limit_event"}) == []
    assert limits.parse({"rate_limit_info": {}}) == []
    assert limits.parse("not a mapping") == []  # type: ignore[arg-type]
    assert limits.parse({"rate_limit_info": {"rateLimitType": "five_hour", "utilization": True}})[0]["used"] is None


def test_the_agent_stream_hands_its_limit_line_to_the_sink():
    seen = []
    limits.set_sink(lambda agent, rows: seen.append((agent, rows)))
    try:
        harness.narrate({"type": "rate_limit_event", "rate_limit_info": {
            "rateLimitType": "five_hour", "utilization": 0.3}})
    finally:
        limits.set_sink(None)
    assert seen and seen[0][0] == "claude-code" and seen[0][1][0]["used"] == 0.3
    assert isinstance(seen[0][1][0]["seen_at"], int), "kept with when it was said"


# ── the meters ───────────────────────────────────────────────────────────


def test_a_use_is_counted_in_the_windows_it_falls_in(tmp_path):
    conn = state.connect(tmp_path / "app.sqlite")
    put(conn, 1, "llm_api", source="api", model="m1", tokens_in=100, tokens_out=40, usd=0.02)
    put(conn, 6, "llm_api", source="api", model="m1", tokens_in=10, tokens_out=5, usd=0.01)
    put(conn, 200, "llm_api", source="api", model="m1", tokens_in=1, tokens_out=1, usd=0.5)
    out = usage.meters(conn)["resources"]["llm_api"]["windows"]
    assert out["5h"]["tokens_in"] == 100 and out["5h"]["usd"] == 0.02
    assert out["24h"]["tokens_in"] == 110 and out["24h"]["usd"] == 0.03
    assert out["7d"]["calls"] == 2, "a use 200 hours back is outside the week"
    assert out["30d"]["calls"] == 3


def test_a_blank_is_not_a_zero_and_a_sum_counts_only_what_was_counted(tmp_path):
    conn = state.connect(tmp_path / "app.sqlite")
    put(conn, 1, "cli_agent", source="claude-code")  # nobody counted this one
    put(conn, 2, "cli_agent", source="claude-code", tokens=500)
    cli = usage.meters(conn)["resources"]["cli_agent"]["windows"]["24h"]
    assert cli["usd"] is None, "a subscription agent prices nothing, and nothing is not $0.00"
    assert cli["tokens"] == 500 and cli["rows"] == 2 and cli["rows_tokenised"] == 1


def test_a_resource_never_used_says_so(tmp_path):
    conn = state.connect(tmp_path / "app.sqlite")
    put(conn, 1, "web_search", source="exa", ok=1)
    out = usage.meters(conn)["resources"]
    assert out["web_search"]["used"] is True
    assert out["llm_api"]["used"] is False and out["local_model"]["used"] is False


def test_a_search_is_filed_with_its_provider_and_whether_it_found_anything(tmp_path):
    path = tmp_path / "app.sqlite"
    provider = websearch.KNOWN[0]
    websearch.record(path, provider, "ok")
    websearch.record(path, provider, "empty")
    conn = state.connect(path)
    search = usage.meters(conn)["resources"]["web_search"]
    assert search["windows"]["5h"]["calls"] == 2 and search["windows"]["5h"]["misses"] == 1
    assert search["by_source"][0]["source"] == provider


def test_each_agent_is_filed_under_the_thing_it_used():
    assert usage.resource_of("local") == "local_model"
    assert usage.resource_of("mistral-api") == "llm_api"
    assert usage.resource_of(plane="api") == "llm_api"
    assert usage.resource_of("claude-code") == "cli_agent"
    assert usage.resource_of("codex", "agent") == "cli_agent"


def test_the_route_serves_the_meters_and_what_the_agent_last_said(tmp_path):
    app_client = client(tmp_path)
    limits.observe("claude-code", {"rate_limit_info": {
        "rateLimitType": "five_hour", "utilization": 0.62, "resetsAt": 1_800_000_000, "status": "allowed"}})
    limits.observe("claude-code", {"rate_limit_info": {"rateLimitType": "seven_day", "utilization": 0.2}})
    body = app_client.get("/api/usage/meters").json()
    assert body["windows"] == ["5h", "24h", "7d", "30d"]
    said = body["resources"]["cli_agent"]["limits"]["claude-code"]
    assert said["five_hour"]["used"] == 0.62 and said["seven_day"]["used"] == 0.2
    assert said["five_hour"]["resets_at"] == 1_800_000_000.0
    limits.set_sink(None)


def test_a_failing_meter_never_fails_the_caller(tmp_path):
    usage.record(tmp_path / "missing" / "\0bad", "llm_api")  # an unusable path
    usage.record(None, "llm_api")
    usage.record(tmp_path / "app.sqlite", "not_a_resource")
    limits.observe("claude-code", {"rate_limit_info": {"rateLimitType": "five_hour", "utilization": 0.1}})
