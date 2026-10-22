"""One case through the real chat turn, as the reader's own stack answers it.

The thing under test is `tasks.chat_ask`, the turn the Chat screen runs: the
brief, the mode rules, the ranking of what the search returned, the reader's
agent and the reader's search provider, all as Settings has them. Only the
state is a copy (`sandbox`), so a run leaves the reader's history alone.

An answerer is anything with `answer(case) -> Answer`; the fakes the tests use
are the same shape.
"""

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

from app import prefs
from app.tuning import agents as agent_mod
from app.tuning.sandbox import sandbox
from app.web import state

if TYPE_CHECKING:
    from app.web.jobs import Progress

#: One case's ceiling. A chat turn is a few agent calls and a search or two.
CASE_TIMEOUT = 300.0


@dataclass
class Answer:
    text: str = ""
    read_urls: list[str] = field(default_factory=list)
    agent: dict = field(default_factory=dict)
    search_provider: str = ""
    seconds: float = 0.0
    tokens: int | None = None
    usd: float | None = None
    error: str = ""
    log: list[str] = field(default_factory=list)
    asked_question: bool = False
    verification: dict = field(default_factory=dict)


class _Deadline(Exception):
    """The case ran past its ceiling."""


class ChatAnswerer:
    """The reader's preferred agent and search provider, answering one case."""

    def __init__(self, reader_app_state: Path, preference: agent_mod.Preference, *,
                 store_path: Path | None = None, timeout: float = CASE_TIMEOUT,
                 override_agent: bool = False, override_search: bool = False):
        self.reader_app_state = Path(reader_app_state)
        self.preference = preference
        self.store_path = store_path
        self.timeout = timeout
        self._overrides: dict = {}
        if override_agent:
            self._overrides[prefs.HARNESS] = preference.agent.id
        if override_search and preference.search_provider != agent_mod.DEFAULT_SEARCH:
            self._overrides[prefs.SEARCH] = preference.search_provider

    def answer(self, case: dict) -> Answer:
        from app import bench, turnusage
        from app.web import tasks

        meters: list = []

        class Recording(turnusage.TurnUsage):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                meters.append(self)

        started = time.monotonic()

        def check() -> None:
            if time.monotonic() - started > self.timeout:
                raise _Deadline()

        out = Answer(agent=self.preference.agent.public(),
                     search_provider=self.preference.search_provider)
        with sandbox(self.reader_app_state, store_path=self.store_path,
                     overrides=self._overrides) as settings:
            conn = state.connect(settings.app_state_path)
            try:
                thread = state.create_chat_thread(conn, case["id"])
                for turn in case.get("history") or []:
                    state.add_chat_message(conn, thread["thread_id"],
                                           role="reader" if turn.get("role") == "reader" else "agent",
                                           text=str(turn.get("text") or ""))
                message = state.add_chat_message(conn, thread["thread_id"], role="reader",
                                                 text=case["question"])
                params = {"thread_id": thread["thread_id"], "message_id": message["message_id"],
                          "text": case["question"],
                          "harness": self._overrides.get(prefs.HARNESS, ""),
                          "backend": "local" if self._overrides.get(prefs.HARNESS) == agent_mod.LOCAL
                          else "harness"}
                job_id = state.create_job(conn, "chat_ask", params)
            finally:
                conn.close()
            silent = bench._Silent(check)
            progress = cast("Progress", silent)
            silent.job_id = job_id
            returned = None
            from unittest import mock

            try:
                with mock.patch.object(turnusage, "TurnUsage", Recording):
                    returned = tasks.chat_ask(settings, params, progress)
            except _Deadline:
                out.error = f"timeout: the case ran past {self.timeout:g} s"
            except Exception as error:  # noqa: BLE001 - a failed run is a measurement
                out.error = f"{type(error).__name__}: {error}"
        out.seconds = round(time.monotonic() - started, 2)
        result = returned if isinstance(returned, dict) and returned else silent.result
        if isinstance(result, dict):
            self._read(result, out)
        if meters:
            usage = meters[-1].snapshot()
            out.tokens, out.usd = usage.get("tokens"), usage.get("spent_usd")
        out.log = list(silent.lines)[-40:]
        return out

    @staticmethod
    def _read(result: dict, out: Answer) -> None:
        """What the chat turn produced, as an `Answer`'s fields."""
        questions = result.get("questions") or []
        if questions and not result.get("answer"):
            out.text, out.asked_question = str(questions[0].get("ask") or ""), True
        else:
            out.text = str(result.get("answer") or "")
        read = [str(url) for url in result.get("sources") or [] if str(url).startswith(("http://", "https://"))]
        for item in result.get("activity") or []:
            if (isinstance(item, dict) and item.get("kind") == "read" and item.get("state") == "done"
                    and str(item.get("url") or "").startswith(("http://", "https://"))):
                read.append(str(item["url"]))
        out.read_urls = list(dict.fromkeys(read))
        agent = result.get("agent")
        if isinstance(agent, dict) and agent.get("id"):
            out.agent = {key: str(agent.get(key) or "") for key in ("id", "label", "model")}
        out.verification = result.get("verification") or {}
