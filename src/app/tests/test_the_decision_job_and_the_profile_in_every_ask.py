"""The agent is asked to decide, with the reader's profile, and may not move the winner for free."""

import pytest

from app import advice, buyer, providers
from app.web import state, tasks
from app.web.settings import Settings


class _Progress:
    job_id = "job-9"

    def log(self, line): pass
    def set(self, *a, **k): pass
    def check(self): pass
    def partial(self, result): pass


@pytest.fixture
def settings(tmp_path):
    return Settings(store_path=tmp_path / "k.sqlite", app_state_path=tmp_path / "app.sqlite",
                    analysis_log_path=tmp_path / "a.jsonl")


class Researcher:
    """A coding agent: replies once and remembers the prompt it was given."""
    harness = type("H", (), {"id": "codex", "label": "Codex", "protocol": ""})()
    requested_model = "codex"
    sources: list = []

    def __init__(self, reply="**Buy: Kettle B** — no known faults.\nSources: https://r.example/b"):
        self.reply, self.prompt = reply, ""

    def ask_followup(self, prompt, product="", question=""):
        self.prompt = prompt
        return self.reply

    def ask(self, prompt, **_):
        self.prompt = prompt
        return self.reply


def wire(monkeypatch, researcher):
    monkeypatch.setattr(tasks, "_use_local_ask", lambda *a, **k: False)
    monkeypatch.setattr(providers, "agent_ready", lambda *a, **k: True)
    monkeypatch.setattr(providers, "harness_researcher", lambda **_kw: researcher)


def seed(settings, label, url, price, claims=()):
    conn = state.connect(settings.app_state_path)
    request = {"url": url, "title": label, "fields": {"ld:price": str(price), "ld:priceCurrency": "EUR"}}
    lookup_id = state.record_lookup(conn, source="extension", label=label, request=request,
                                    response={"claims": list(claims)})
    conn.close()
    return lookup_id


def test_a_decision_brief_carries_the_ranking_the_profile_and_the_shape(settings, monkeypatch):
    researcher = Researcher()
    wire(monkeypatch, researcher)
    conn = state.connect(settings.app_state_path)
    buyer.save(conn, {"avoid": ["Acme"], "priorities": {"durability": 5}})
    conn.close()
    a = seed(settings, "Kettle A", "https://a.test/p/1", 60, [{"title": "Element fails", "severity": "high"}])
    b = seed(settings, "Kettle B", "https://b.test/p/1", 66)

    result = tasks.buyer_advice(settings, {"mode": "pick", "lookup_ids": [a, b]}, _Progress())

    assert result["ranking"]["picked"]["name"] == "Kettle B"
    assert result["answer"].startswith("**Buy: Kettle B**")
    assert result["sources"] == [{"url": "https://r.example/b", "domain": "r.example"}]
    for needle in ("KRIKO'S PICK: Kettle B", "Element fails", "**Buy: <product>**",
                   "Commit: name what you would buy", "Keep its winner unless", buyer.MARK, "Avoid: Acme"):
        assert needle in researcher.prompt
    assert researcher.prompt.count(buyer.MARK) == 1
    kept = state.connect(settings.app_state_path).execute("SELECT winner_name FROM picks").fetchall()
    assert [row["winner_name"] for row in kept] == ["Kettle B"]
    assert result["pick"]["winner"] == "Kettle B"


def test_a_debate_names_three_voices_and_is_not_kept_as_a_pick(settings, monkeypatch):
    researcher = Researcher("**The sceptic** ...")
    wire(monkeypatch, researcher)
    a = seed(settings, "Kettle A", "https://a.test/p/1", 60)
    b = seed(settings, "Kettle B", "https://b.test/p/1", 66)
    result = tasks.buyer_advice(settings, {"mode": "debate", "lookup_ids": [a, b]}, _Progress())
    for voice in ("The sceptic", "The bargain hunter", "The durability nerd", "Where they split"):
        assert voice in researcher.prompt
    assert result["pick"] is None
    assert state.connect(settings.app_state_path).execute("SELECT COUNT(*) FROM picks").fetchone()[0] == 0


def test_timing_and_cost_of_owning_need_only_one_product_and_carry_the_price_history(settings, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from app import pricewatch

    researcher = Researcher("**Wait until the next sale** — usual price. Sources: https://r.example/t")
    wire(monkeypatch, researcher)
    a = seed(settings, "Kettle A", "https://a.test/p/1", 60)
    conn = state.connect(settings.app_state_path)
    now = datetime.now(UTC)
    for day, price in enumerate([60, 61, 60, 62, 60]):
        pricewatch.record(conn, "https://a.test/p/1", "Kettle A", {"price": price, "currency": "EUR"},
                          now=now - timedelta(days=30 - day * 5))
    conn.close()
    tasks.buyer_advice(settings, {"mode": "timing", "lookup_ids": [a]}, _Progress())
    assert "PRICE HISTORY" in researcher.prompt and "Kettle A: now 60 EUR" in researcher.prompt
    assert "successor or refresh" in researcher.prompt
    tasks.buyer_advice(settings, {"mode": "tco", "lookup_ids": [a]}, _Progress())
    assert "three years" in researcher.prompt


def test_a_decision_needs_enough_saved_checks_and_a_known_mode(settings, monkeypatch):
    wire(monkeypatch, Researcher())
    a = seed(settings, "Kettle A", "https://a.test/p/1", 60)
    with pytest.raises(ValueError, match="needs 2 saved checks"):
        tasks.buyer_advice(settings, {"mode": "pick", "lookup_ids": [a]}, _Progress())
    with pytest.raises(ValueError, match="mode is one of"):
        tasks.buyer_advice(settings, {"mode": "poem", "lookup_ids": [a]}, _Progress())


def test_an_empty_reply_is_an_error_not_a_kept_pick(settings, monkeypatch):
    wire(monkeypatch, Researcher(""))
    a = seed(settings, "Kettle A", "https://a.test/p/1", 60)
    b = seed(settings, "Kettle B", "https://b.test/p/1", 66)
    with pytest.raises(ValueError, match="did not complete the follow-up"):
        tasks.buyer_advice(settings, {"mode": "pick", "lookup_ids": [a, b]}, _Progress())
    assert state.connect(settings.app_state_path).execute("SELECT COUNT(*) FROM picks").fetchone()[0] == 0


def test_every_ask_about_a_saved_check_carries_the_profile_and_a_silent_reader_gets_none(settings, monkeypatch):
    researcher = Researcher("Fine. Sources: https://r.example/x")
    wire(monkeypatch, researcher)
    tasks._ask_about_checks(settings, {}, _Progress(), "Is it any good?", follow_up=True)
    assert buyer.MARK not in researcher.prompt
    conn = state.connect(settings.app_state_path)
    buyer.save(conn, {"must": ["usb-c"]})
    conn.close()
    tasks._ask_about_checks(settings, {}, _Progress(), "Is it any good?", follow_up=True)
    assert "Must have: usb-c" in researcher.prompt and researcher.prompt.count(buyer.MARK) == 1


def test_the_modes_are_the_four_the_screens_offer():
    assert advice.MODES == ("pick", "debate", "tco", "timing")
    with pytest.raises(ValueError):
        advice.brief("poem", result={"ranked": []})
