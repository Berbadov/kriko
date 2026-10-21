"""Fakes for the tuning tests: an answerer, a grader agent and a web, none of which spend anything."""

import json

from app.tuning import agents as agent_mod
from app.tuning import grade
from app.tuning.answer import Answer

PAGE = ("The Acme Widget MK2 has a stainless steel pump housing rated for 8 bar. "
        "Owners report the seal failed after a month of use. The tyres carry a separate warranty.")
URL = "https://maker.example/widget-mk2"
PAGES = {URL: PAGE, "https://forum.example/thread": "Forum thread: the MK2 seal failed after a month."}

ANSWERER = agent_mod.AgentRef("codex", "Codex", "harness", "model-a")
GRADER = agent_mod.AgentRef("claude-code", "Claude Code", "harness", "model-b")
LOCAL = agent_mod.AgentRef("local", "Local model", "local", "qwen-small")

CASE = {"id": "widget-heavy", "source": "bench", "question": "Does the Acme Widget MK2 pump housing rust?",
        "category": "widget", "complexity": "heavy", "primary_domains": ["maker.example"], "primary_min": 1,
        "criteria": [{"id": "material", "fact": "The housing is stainless steel.", "critical": True},
                     {"id": "rating", "fact": "The pump is rated for 8 bar."}],
        "references": [URL]}
CLARIFY = {"id": "widget-identity", "source": "bench",
           "question": "Listing says only Acme Widget. Can I submerge it? Ask what you need first.",
           "complexity": "identity", "expected_action": "clarify", "primary_domains": [], "primary_min": 0,
           "criteria": [{"id": "ask", "fact": "Ask which variant it is.", "critical": True}]}
CHAT = {"id": "chat-abc-1", "source": "chat", "question": "Is the Acme Widget MK2 any good for a small boat?",
        "criteria": [], "primary_domains": [], "primary_min": 0, "complexity": "chat"}


def good_answer(**over) -> Answer:
    base = dict(text=f"The MK2 housing is stainless steel and rated for 8 bar [{URL}]. "
                     "The seal failed in a month for owners.",
                read_urls=[URL], agent=ANSWERER.public(), search_provider="searchprov-x", seconds=3.0,
                tokens=1200, usd=0.01, log=["step: searching", "REASONING-LINE the agent weighed two plans"])
    base.update(over)
    return Answer(**base)


class FakeAnswerer:
    def __init__(self, answers: dict | None = None, default: Answer | None = None):
        self.answers = answers or {}
        self.default = default
        self.asked: list[str] = []

    def answer(self, case):
        self.asked.append(case["id"])
        found = self.answers.get(case["id"], self.default)
        if isinstance(found, Exception):
            raise found
        return found if found is not None else good_answer()


def verdict(**over) -> dict:
    """What a sound grader says about `good_answer` on `CASE`."""
    base = {"facts": [{"id": "material", "status": "met", "url": URL,
                       "quote": "a stainless steel pump housing", "reason": "stated"},
                      {"id": "rating", "status": "met", "url": URL,
                       "quote": "rated for 8 bar", "reason": "stated"}],
            "claims": [{"text": "The housing is stainless steel", "supported": "yes", "url": URL,
                        "quote": "stainless steel pump housing rated for 8 bar"}],
            "identity": {"matches": True, "reason": "the MK2"},
            "asked_for_clarification": False, "requirements_ignored": [],
            "summary": "Both facts are stated and carried by the maker's page."}
    base.update(over)
    return base


def sound(packet: dict, **over) -> dict:
    """A sound grader's verdict for whatever rubric the packet carries."""
    clarify = packet.get("expected_action") == "clarify"
    reply = verdict(
        facts=[{"id": one["id"], "status": "met", "url": "" if clarify else URL,
                "quote": "" if clarify else "stainless steel pump housing", "reason": "stated"}
               for one in packet["rubric"]],
        asked_for_clarification=clarify)
    reply.update(over)
    return reply


class FakeGraderAgent:
    """An opened agent.

    It replies from `script` (question -> verdict dict or raw text); else with
    `default` (a whole verdict or raw text); else with a sound verdict for the
    rubric it was handed, `overrides` applied on top.
    """

    def __init__(self, script: dict | None = None, ref=GRADER, default=None, overrides: dict | None = None,
                 raw: str | None = None):
        self.ref = ref
        self.script = script or {}
        self.default = default
        self.overrides = overrides or {}
        self.raw = raw
        self.prompts: list[str] = []
        self.spent = 0

    def ask(self, prompt: str) -> str:
        self.prompts.append(prompt)
        self.spent += 100
        packet = json.loads(prompt.split(grade.GRADER_SYSTEM, 1)[1])
        found = self.script.get(packet["question"])
        if found is None:
            found = (self.raw if self.raw is not None else self.default if self.default is not None
                     else sound(packet, **self.overrides))
        return found if isinstance(found, str) else "```json\n" + json.dumps(found) + "\n```"

    def usage(self) -> dict:
        return {"tokens": self.spent, "usd": None}


def fetch(url: str):
    return PAGES.get(url, "")
