"""What is under test: one model, reached one way.

A candidate has three facts — **kind** (how it is reached), **model** (what
answers), and **harness** (which CLI drives it, when one does) — and its `id`
is exactly those three, spelled so a person can type it:

    local:qwen3.5:4b                    Ollama on this machine
    local:gemma3n:e2b                   the same, a different model
    harness:mistral-vibe@glm-5-3        the Mistral CLI, driving GLM-5.3
    harness:claude-code                 the Claude CLI on its own default model
    api:gpt-4o-mini                     a paid endpoint, when a key is present

The id is the primary key of every table the report prints, and it round-trips
through `parse`, so a result can be reproduced by pasting one string.

**Discovery is a convenience, never an assumption.** `discover()` reports what
this machine can actually reach *right now* — the models the local server lists,
the CLIs found on PATH, the catalogue models whose key is present — and it never
invents a candidate it could not run. A name nobody owns still parses, because a
model released this morning is exactly the one a reader wants to measure before
the catalogue catches up; it simply fails loudly at run time rather than being
refused at the door.
"""

from dataclasses import dataclass, field

#: How a model is reached. A closed engineering vocabulary: three genuinely
#: different transports, not a list that grows with coverage.
KINDS = ("local", "harness", "api")

KIND_MEANING = {
    "local": "a model on this machine; no key, no account",
    "harness": "a coding-agent CLI, on its own subscription and its own prompt",
    "api": "a paid per-token endpoint",
}


@dataclass(frozen=True)
class Candidate:
    """One model, reached one way. Immutable, so it can key a dict."""

    kind: str
    model: str = ""
    harness: str = ""
    #: What this machine can say about it, filled by `discover` and empty for a
    #: name typed by hand. Reported, never required.
    detail: str = ""
    #: Set by `discover` for a local candidate: the base URL the model was
    #: listed on, so a run in another process reaches the same server.
    base_url: str = ""
    options: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        """The string that names this candidate everywhere."""
        if self.kind == "harness":
            return f"harness:{self.harness}" + (f"@{self.model}" if self.model else "")
        return f"{self.kind}:{self.model}"

    @property
    def label(self) -> str:
        """One sentence for a report row, in the reader's words."""
        where = KIND_MEANING.get(self.kind, self.kind)
        model = self.model or ("its own default model" if self.kind == "harness" else "?")
        if self.kind == "harness":
            return f"{model} via {self.harness} — {where}"
        return f"{model} — {where}"

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "model": self.model,
            "harness": self.harness,
            "label": self.label,
            "detail": self.detail,
            "base_url": self.base_url,
            "options": dict(self.options),
        }


class UnknownCandidate(ValueError):
    """The spec names a kind this benchmark cannot reach."""


def parse(spec: str) -> Candidate:
    """`"harness:mistral-vibe@glm-5-3"` → a `Candidate`.

    Split on the **first** colon only, because a local model name contains
    colons of its own (`qwen3.5:4b`, `gemma3n:e2b`) and a parser that split on
    every one would read the tag as a kind and refuse the candidate. The
    harness separator is the **last** `@` for the same reason in reverse: a
    model name may carry a version suffix, and the CLI's own id never does.
    """
    text = str(spec or "").strip()
    if not text:
        raise UnknownCandidate("empty candidate spec")
    kind, sep, rest = text.partition(":")
    kind = kind.strip().lower()
    rest = rest.strip() if sep else ""
    if kind not in KINDS:
        raise UnknownCandidate(
            f"unknown candidate kind {kind!r} in {text!r}; expected one of "
            + ", ".join(KINDS)
            + " — for example local:qwen3.5:4b"
        )
    if kind == "harness":
        if not rest:
            raise UnknownCandidate(
                f"{text!r} names no CLI; write harness:<cli>[@<model>], "
                "for example harness:mistral-vibe@glm-5-3"
            )
        harness, at, model = rest.rpartition("@")
        if not at:
            return Candidate(kind="harness", model="", harness=rest)
        return Candidate(kind="harness", model=model.strip(), harness=harness.strip())
    if not rest:
        raise UnknownCandidate(
            f"{text!r} names no model; write {kind}:<model>"
        )
    return Candidate(kind=kind, model=rest)


def parse_many(specs) -> list[Candidate]:
    """Several specs, in order, each parsed once and de-duplicated.

    A list or a comma-separated string, because both are how a person writes it
    — a CLI flag takes the string, a config file takes the list, and neither
    should have to learn the other's syntax.
    """
    items = ([specs] if isinstance(specs, str) else list(specs or []))
    found: list[Candidate] = []
    seen: set[str] = set()
    for item in items:
        for piece in str(item).split(","):
            piece = piece.strip()
            if not piece:
                continue
            one = parse(piece)
            if one.id not in seen:
                seen.add(one.id)
                found.append(one)
    return found


def local_candidates(app_state_path=None) -> list[Candidate]:
    """Every model the local server lists, as candidates.

    Silent when the server is down or unresolvable: "no local models" is a
    fact about this machine, and `discover` reports it by leaving them out.
    """
    try:
        from app import localplane

        resolved = localplane.resolve(app_state_path, with_search=False)
    except Exception:  # noqa: BLE001 — discovery never breaks a listing
        return []
    if not resolved.get("ready"):
        return []
    url = str(resolved.get("url") or "")
    name = str(resolved.get("name") or "local server")
    return [
        Candidate(kind="local", model=str(model), base_url=url,
                  detail=f"listed by {name} at {url}")
        for model in resolved.get("models") or []
    ]


def harness_candidates(app_state_path=None) -> list[Candidate]:
    """Every coding-agent CLI found on this machine.

    Two candidates per CLI when it names its own models — one per model, plus
    the CLI's default — because "the CLI's default" and "the CLI told to use
    X" are different models and a table that averaged them would hide exactly
    the choice being made. A CLI that lists nothing (the common case when it is
    not logged in yet) still yields its default, since the run itself will say
    whether it can answer.
    """
    try:
        from app.providers import harness

        found = harness.available()
    except Exception:  # noqa: BLE001 — discovery never breaks a listing
        return []
    out: list[Candidate] = []
    for one in found:
        identifier = str(getattr(one, "id", "") or "")
        if not identifier:
            continue
        label = str(getattr(one, "label", "") or identifier)
        try:
            models = list(harness.models_for(one) or [])
        except Exception:  # noqa: BLE001 — a model list never breaks a listing
            models = []
        out.append(Candidate(kind="harness", harness=identifier, model="",
                             detail=f"{label}, its own default model"))
        for model in models:
            out.append(Candidate(kind="harness", harness=identifier,
                                 model=str(model), detail=f"{label}, model {model}"))
    return out


def api_candidates() -> list[Candidate]:
    """Catalogue models this machine holds a key for.

    Only with a key: listing a paid model nobody can call is how a benchmark
    fills with rows that only ever say "no key".
    """
    try:
        from app import keys, modelcatalogue

        if not keys.ready():
            return []
        names = list(modelcatalogue.load())
    except Exception:  # noqa: BLE001 — discovery never breaks a listing
        return []
    return [
        Candidate(kind="api", model=str(name),
                  detail=f"{modelcatalogue.provider_for(name)} via the "
                         "configured endpoint")
        for name in names
    ]


def discover(app_state_path=None, *, kinds=None) -> list[Candidate]:
    """Everything this machine can measure right now, in a stable order.

    Ordered local, harness, api — cheapest and most private first, which is the
    order the phone's decision will weigh them in — and inside each kind by the
    order the machine listed them, so two runs print the same table.
    """
    wanted = [str(one) for one in (kinds or KINDS)]
    out: list[Candidate] = []
    if "local" in wanted:
        out += local_candidates(app_state_path)
    if "harness" in wanted:
        out += harness_candidates(app_state_path)
    if "api" in wanted:
        out += api_candidates()
    return out
