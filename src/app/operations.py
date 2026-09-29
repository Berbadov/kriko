"""Recording what an agent is doing, while it does it.

An **operation** is one unit of agent-driven work on the knowledge — research,
an agenda batch, a pack authored, a re-check, a read. `docs/AGENT_OPERATIONS.md`
holds the vocabulary; this module is the recorder behind it.

**Why it exists.** B121 made a run that *Kriko starts* visible while it runs.
But the door the reader actually prefers is their own coding agent talking to
the MCP server — the terminal is for the person, the app is for the operations
— and that door was visible only afterwards, only as a `submissions` row, and
only when the operation happened to be a submission. A `lookup`, a
`research_brief`, a `draft_pack` left nothing at all. So the app could not
answer the simplest question anyone asks of an agent: *what is it doing right
now, and what did it just ask me?*

Three rules, each of which is a bug that would otherwise arrive later:

* **Recording never changes the outcome.** Every failure here is swallowed. A
  reader losing a feed row is a worse feed; a researcher losing an accepted
  finding because the feed could not be written is a defect. Same reasoning as
  `findings.log_submission`.
* **Payloads are summarised, never stored.** `submit_findings` carries whole
  pages of `document_text`, and keeping them here would duplicate the
  `documents` table and make this the largest thing in `app.sqlite`. `digest()`
  elides any long string and says how many characters it dropped, so a reader
  sees the shape of the call without the app hoarding its body.
* **The row opens before the work.** A call that is still running is a row that
  says `running`. That is the difference between a feed and a log, and it is
  also what makes a hung tool call visible instead of silent.
"""

import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import TypedDict


class _Outcome(TypedDict):
    state: str
    response: str
    error: str
    usd: float | None
    tokens: int | None

#: Longer than this and a string is replaced by its own measurement. Generous
#: enough that a query, a URL or a title survives whole; small enough that a
#: page cannot.
MAX_FIELD_CHARS = 400

#: And the ceiling on the whole summary, after eliding. A tool with fifty
#: arguments is not a reason for a fifty-kilobyte row.
MAX_SUMMARY_CHARS = 4000

#: Field *names* that are never worth keeping verbatim, whatever tool put them
#: there. Matched case-insensitively as a substring of the key, not the value —
#: no tool in this codebase asks an agent for a credential today, but this
#: table is a feed nothing else redacts and every reader's history keeps
#: forever, so a future argument named `api_key` must not become a row on
#: disk merely because nobody remembered to teach this module about it too.
SECRET_KEY_NEEDLES = ("key", "token", "secret", "password", "authorization", "credential")


def _looks_secret(name: str) -> bool:
    low = name.lower()
    return any(needle in low for needle in SECRET_KEY_NEEDLES)

#: What each MCP tool is, in the operation vocabulary. Unlisted tools are
#: `read`, which is what the majority of them are and the safest thing to
#: assume about a name nobody has classified — a closed engineering vocabulary,
#: not data that grows with pack coverage.
KINDS = {
    # Job kinds, which are the same operations arriving through the other
    # door — `research` is `research` whether a reader pressed it or an agent
    # asked for it, and a feed that called them different things would hide
    # exactly the comparison this table exists to make possible.
    "research": "research",
    "agenda_run": "agenda",
    "pack_author": "author",
    "quick_look": "research",
    "pack_amend": "author",
    "verify": "recheck",
    "pack_build": "author",
    "pack_update": "write",
    "submit_findings": "research",
    "research_brief": "research",
    "research_agenda": "agenda",
    "draft_pack": "author",
    "write_draft_file": "author",
    "build_draft": "author",
    "install_pack": "write",
    "set_pack_enabled": "write",
}


def kind_of(name: str) -> str:
    return KINDS.get(name, "read")


def digest(value, *, depth: int = 0):
    """One argument or result, small enough to keep and honest about it."""
    if isinstance(value, str):
        if len(value) <= MAX_FIELD_CHARS:
            return value
        return f"{value[:MAX_FIELD_CHARS]}… (+{len(value) - MAX_FIELD_CHARS} chars)"
    if isinstance(value, dict):
        if depth >= 3:
            return f"<{len(value)} field(s)>"
        return {
            str(k): ("<redacted>" if _looks_secret(str(k)) else digest(v, depth=depth + 1))
            for k, v in list(value.items())[:40]
        }
    if isinstance(value, (list, tuple)):
        if depth >= 3:
            return f"<{len(value)} item(s)>"
        kept = [digest(v, depth=depth + 1) for v in value[:20]]
        if len(value) > 20:
            kept.append(f"… (+{len(value) - 20} more)")
        return kept
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return digest(str(value), depth=depth)


def metered(result) -> tuple[float | None, int | None]:
    """What a handler's own result says it spent, when it says anything.

    Reads the two keys the research handlers already report rather than
    threading a meter through every plane: a handler that counted writes them,
    one that did not leaves them absent, and absent stays absent all the way
    to the column. A run on the free plane costs nothing and is not the same
    fact as a run nobody priced, so neither becomes a zero here.
    """
    if not isinstance(result, dict):
        return None, None
    usd = result.get("spent_usd")
    tokens = result.get("tokens")
    try:
        usd = float(usd) if usd is not None else None
    except (TypeError, ValueError):
        usd = None
    try:
        tokens = int(tokens) if tokens is not None else None
    except (TypeError, ValueError):
        tokens = None
    return usd, tokens


def summarise(value) -> str:
    try:
        text = json.dumps(digest(value), default=str)
    except Exception:  # noqa: BLE001 — a payload that will not serialise is
        # still an operation worth recording.
        text = "<unserialisable>"
    return text if len(text) <= MAX_SUMMARY_CHARS else text[:MAX_SUMMARY_CHARS] + "…"


@contextmanager
def record(
    app_state_path=None,
    *,
    conn=None,
    door: str,
    name: str,
    kind: str = "",
    arguments=None,
    job_id: str = "",
):
    """Open a row, run the body, close the row. Never raises on its own account.

    Used as a context manager so an exception inside the body is recorded as a
    `failed` operation and then re-raised untouched: the caller's error
    handling is not this module's business.

    `conn`, when given, is an already-open app.sqlite connection this call
    reuses instead of opening (and later closing) its own — pass `conn` from
    a caller that already holds one (e.g. a FastAPI handler with
    `Depends(get_app_state)`) rather than `app_state_path`. Every call site
    used to pay for a second connect and two more commits on top of whatever
    the caller already opened, which on `/api/analyze` — run on every single
    lookup — cost more than the lookup itself (B145 apicode-2). A caller with
    no live connection (the CLI, MCP, a background job) still passes
    `app_state_path` and gets the original one-shot behaviour.
    """
    from app.web import state

    owns_conn = conn is None
    op_id = 0
    started = time.monotonic()
    try:
        if owns_conn:
            conn = state.connect(Path(app_state_path))
        op_id = state.open_operation(
            conn,
            door=door,
            kind=kind or kind_of(name),
            name=name,
            subject_id=str((arguments or {}).get("subject_id") or ""),
            pack_id=str((arguments or {}).get("pack_id") or ""),
            request=summarise(arguments or {}),
            # Empty for every door but `job`, and that emptiness is what tells
            # the feed which running rows it may offer to stop: a job belongs
            # to the runner in this process, an MCP call belongs to the process
            # that made it.
            job_id=job_id,
        )
    except Exception:  # noqa: BLE001 — see the module docstring
        op_id = 0
        if owns_conn:
            conn = None

    outcome: _Outcome = {
        "state": "ok",
        "response": "",
        "error": "",
        # Left as None unless something actually counted one. A plane that
        # spends no money and a plane whose spend nobody measured are
        # different facts, and a zero here would merge them -- which is the
        # shape of lie the cost column exists to avoid.
        "usd": None,
        "tokens": None,
    }
    try:
        yield outcome
    except BaseException as exc:  # noqa: BLE001 — recorded, then re-raised
        outcome["state"] = "failed"
        outcome["error"] = f"{type(exc).__name__}: {exc}"[:MAX_SUMMARY_CHARS]
        raise
    finally:
        if conn is not None and op_id:
            try:
                state.close_operation(
                    conn,
                    op_id,
                    state=outcome["state"],
                    response=outcome["response"],
                    error=outcome["error"],
                    ms=int((time.monotonic() - started) * 1000),
                    usd=outcome["usd"],
                    tokens=outcome["tokens"],
                )
            except Exception:  # noqa: BLE001
                pass
        if owns_conn and conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
