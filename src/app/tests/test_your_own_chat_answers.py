"""A reader with only a chat in a browser tab can still get a quick look.

The reader's worry: "for everyday users we have no solution. For the people
that have no llm subscription and just using llms as a normal chat". With no
agent, key or local model, every research door ended at a 503. Now the quick
look hands its question to the reader's own chat and checks the pasted answer
against the pages it cites, on this machine.
"""

from __future__ import annotations

import json

import pytest

from app.providers.chat_bridge import CHAT_TAIL, ChatBridge, ChatNotAnswered, cited_urls

PAGE = ("Owners report that the pump seal fails after two winters. The dealer "
        "replaced the seal under warranty in most cases.")


def reply(risks, specs=()):
    return "```json\n" + json.dumps({
        "assumed": "", "category": "pressure washer", "pack": "", "pack_identity": {},
        "specs": list(specs), "risks": risks}) + "\n```"


class Progress:
    job_id = "j"

    def __init__(self, said=(), cancel_after=None):
        self.said = list(said)
        self.lines: list[str] = []
        self.partials: list[dict] = []
        self.asked = 0
        self.cancel_after = cancel_after

    def log(self, line):
        self.lines.append(line)

    def set(self, *args, **kwargs):
        pass

    def check(self):
        if self.cancel_after is not None and self.asked >= self.cancel_after:
            raise RuntimeError("cancelled")

    def replies(self):
        self.asked += 1
        if self.asked < 3:  # the reader takes a moment
            return []
        out, self.said = self.said, []
        return out

    def partial(self, result):
        self.partials.append(result)


def pages(mapping):
    return lambda url: (mapping[url], "") if url in mapping else (None, "the site answered 404")


def test_the_question_is_handed_over_and_the_answer_waited_for():
    answer = reply([{"title": "Seal fails", "why": "", "severity": "high",
                     "url": "https://forum.test/a", "quote": "the pump seal fails after two winters"}])
    progress = Progress(said=[answer])
    bridge = ChatBridge(progress, fetch=pages({"https://forum.test/a": PAGE}),
                        sleep=lambda _: None)

    got = bridge.ask("# Quick look\n\nWidget 3000")

    assert got == answer
    assert progress.partials[0]["chat_prompt"].startswith("# Quick look")
    assert CHAT_TAIL.strip() in progress.partials[0]["chat_prompt"]
    assert progress.asked >= 3, "it waited for the paste rather than answering itself"
    assert bridge.sources == {"https://forum.test/a": PAGE}


def test_only_lines_whose_quote_is_on_its_page_survive():
    from app import quicklook

    answer = reply([
        {"title": "Seal fails", "why": "w", "severity": "high",
         "url": "https://forum.test/a", "quote": "the pump seal fails after two winters"},
        {"title": "Invented", "why": "w", "severity": "high",
         "url": "https://forum.test/a", "quote": "the motor catches fire"},
        {"title": "Unreadable source", "why": "w", "severity": "medium",
         "url": "https://gone.test/x", "quote": "anything at all"},
    ])
    bridge = ChatBridge(Progress(said=[answer]),
                        fetch=pages({"https://forum.test/a": PAGE}), sleep=lambda _: None)

    found = quicklook.parse(bridge.ask("q"), bridge.sources)

    assert [risk["title"] for risk in found["risks"]] == ["Seal fails"]
    assert found["risks"][0]["sources"][0]["grounded"] is True
    assert found["dropped"] == 2


def test_no_paste_in_time_says_so():
    clock = iter(range(0, 10_000, 600))
    bridge = ChatBridge(Progress(), fetch=pages({}), sleep=lambda _: None,
                        wait_seconds=1800, clock=lambda: next(clock))
    with pytest.raises(ChatNotAnswered, match="No answer was pasted"):
        bridge.ask("q")


def test_stopping_the_run_while_it_waits_stops_it():
    bridge = ChatBridge(Progress(cancel_after=1), fetch=pages({}), sleep=lambda _: None)
    with pytest.raises(RuntimeError, match="cancelled"):
        bridge.ask("q")


def test_a_pasted_answer_cannot_make_this_machine_crawl():
    many = [{"title": f"r{i}", "why": "", "severity": "low",
             "url": f"https://site.test/{i}", "quote": "q"} for i in range(40)]
    assert len(cited_urls(reply(many))) == 15
    assert cited_urls("not json at all") == []


def test_the_quick_look_job_runs_on_the_readers_chat(tmp_path, monkeypatch):
    """The whole job, as the panel drives it: the plane says chat, the reader
    pastes, and the result carries only what held up against its page."""
    from app import factcheck
    from app.web import tasks

    monkeypatch.setattr(factcheck, "fetch", pages({"https://forum.test/a": PAGE}))
    monkeypatch.setattr("app.providers.chat_bridge.time.sleep", lambda _: None)
    answer = reply([
        {"title": "Seal fails", "why": "Leaks after two winters.", "check": "Ask about the seal.",
         "severity": "high", "url": "https://forum.test/a",
         "quote": "the pump seal fails after two winters"},
        {"title": "Made up", "why": "", "severity": "high",
         "url": "https://forum.test/a", "quote": "it explodes"},
    ])
    progress = Progress(said=[answer])
    settings = type("S", (), {"store_path": tmp_path / "k.sqlite",
                              "app_state_path": tmp_path / "app.sqlite"})()

    result = tasks.quick_look(settings, {"product": "Widget 3000", "backend": "chat"}, progress)

    assert "Widget 3000" in progress.partials[0]["chat_prompt"]
    assert [risk["title"] for risk in result["risks"]] == ["Seal fails"]
    assert result["cost_basis"] == "own_chat"
    assert result["spent_usd"] is None
    assert any(line.startswith("read: https://forum.test/a") for line in progress.lines)
