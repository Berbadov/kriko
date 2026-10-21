"""Who answers, who grades, and the rule that they are never the same.

The answerer is the reader's *preferred* agent and *preferred* search
provider, read from Settings (`app.prefs`): tuning the engine against some
other stack than the one the reader runs would tune for nobody. The grader is
another agent from the machine's roster. It is never the one that answered
(a model grading its own answer grades its own blind spots) and it is never
shown who answered or how: `grade` builds its prompt from the final answer
text and the fetched evidence only.

If the machine has no second agent, the command stops and says so. It does not
fall back to self-grading; a number from that would look like a measurement
and mean nothing.
"""

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, cast

from app import prefs
from app.web import state

if TYPE_CHECKING:
    from app.web.jobs import Progress

LOCAL = prefs.LOCAL_PICK

#: What the search setting means when it is empty: the chat turn's own default.
DEFAULT_SEARCH = "default (the search service on this machine)"


class AgentUnavailable(RuntimeError):
    """The agent asked for is not here; the text says which are."""


class NoIndependentGrader(AgentUnavailable):
    """No agent other than the answerer is available to grade."""


@dataclass(frozen=True)
class AgentRef:
    id: str
    label: str
    kind: str  # "harness" | "api" | "local"
    model: str = ""

    def public(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Preference:
    """What the reader's Settings say a chat answer is made with."""

    agent: AgentRef
    search_provider: str
    note: str = ""

    def public(self) -> dict:
        return {"agent": self.agent.public(), "search_provider": self.search_provider,
                "note": self.note}


def roster(app_state_path) -> list[AgentRef]:
    """Every agent this machine could use, as `Agents` lists them: installed
    coding-agent CLIs, API agents that have a key, and the local model when
    its server answers."""
    from app import localplane
    from app.providers import agents_available, apiagent

    conn = state.connect(app_state_path)
    try:
        stored = prefs.read(conn)
    finally:
        conn.close()
    found: list[AgentRef] = []
    for one in agents_available():
        api = isinstance(one, apiagent.ApiAgent)
        found.append(AgentRef(one.id, one.label, "api" if api else "harness",
                              stored.get(prefs.harness_model_key(one.id), "")))
    if localplane.is_ready(app_state_path):
        found.append(AgentRef(LOCAL, "Local model", "local", stored.get(prefs.LOCAL_MODEL, "")))
    return found


def read_preference(app_state_path, agents: list[AgentRef], *,
                    agent: str = "", search: str = "") -> Preference:
    """The reader's pick, or an override named on the command line.

    A pick that is not on the roster (an uninstalled CLI) is an error, not a
    quiet substitute: the run would otherwise report numbers for an agent the
    reader did not choose. With no pick at all the first agent on the roster
    answers, as a chat turn would.
    """
    conn = state.connect(app_state_path)
    try:
        stored = prefs.read(conn)
    finally:
        conn.close()
    pick = agent or stored.get(prefs.HARNESS, "")
    note = ""
    if pick:
        found = next((one for one in agents if one.id == pick), None)
        if found is None:
            raise AgentUnavailable(
                f"the agent {pick!r} is not available here "
                f"(available: {', '.join(one.id for one in agents) or 'none'})")
    elif agents:
        found, note = agents[0], "no agent is picked in Settings; the first available one answers"
    else:
        raise AgentUnavailable("no agent is available here: install a coding-agent CLI, "
                               "add an API key or start the local model server")
    return Preference(found, search or stored.get(prefs.SEARCH, "") or DEFAULT_SEARCH, note)


def choose_grader(answerer: AgentRef, agents: list[AgentRef], wanted: str = "") -> AgentRef:
    """An agent that is not the answerer.

    Never the same id; never the same non-empty model name either, since two
    ids can serve one model. With `wanted`, exactly that agent or an error;
    without it, the first other agent on the roster.
    """
    def other(one: AgentRef) -> bool:
        return one.id != answerer.id and not (one.model and one.model == answerer.model)

    if wanted:
        if wanted == answerer.id:
            raise NoIndependentGrader(
                f"{wanted!r} would grade its own answers; name a different grader with --grader")
        found = next((one for one in agents if one.id == wanted), None)
        if found is None:
            raise AgentUnavailable(f"the grader {wanted!r} is not available here")
        if not other(found):
            raise NoIndependentGrader(f"{wanted!r} runs the same model as the answerer")
        return found
    for one in agents:
        if other(one):
            return one
    raise NoIndependentGrader(
        "grading needs a second agent that is not the one answering, and this machine has "
        f"none ({', '.join(one.id for one in agents) or 'no agents'}). Connect another agent "
        "or add a key, then run again. Tuning never lets an agent grade itself.")


@dataclass
class OpenAgent:
    """One agent, opened to answer single prompts with no tools."""

    ref: AgentRef
    _ask: object
    _source: object = None

    def ask(self, prompt: str) -> str:
        return str(self._ask(prompt))  # type: ignore[operator]

    def usage(self) -> dict:
        source = self._source
        tokens = getattr(source, "tokens_used", None)
        usd = getattr(source, "spent", None)
        return {"tokens": tokens if isinstance(tokens, int) and not isinstance(tokens, bool) else None,
                "usd": usd if isinstance(usd, (int, float)) and not isinstance(usd, bool) else None}


def open_agent(ref: AgentRef, settings, *, timeout: float = 240.0) -> OpenAgent:
    """The agent as something that answers a prompt, with its own tools off.

    `settings` is a sandbox's (`sandbox.sandbox`): the reader's preferences are
    in it, so a model or effort chosen for this agent applies to the grading
    as it does to the reader's own use.
    """
    if ref.kind == "local":
        from app.web import tasks
        from app import bench

        completer = tasks._local_structured_completer(
            settings, {"harness": LOCAL, "backend": "local", "timeout_seconds": timeout},
            cast("Progress", bench._Silent()))
        completer.max_tokens = 4096
        return OpenAgent(ref, completer, completer)
    from app.providers import harness_researcher

    researcher = harness_researcher(preferred=ref.id, timeout=timeout,
                                    app_state_path=settings.app_state_path, model=ref.model)
    return OpenAgent(ref, lambda prompt: researcher.ask(prompt, allow_tools=False), researcher)
