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

#: Longer than this and a string is replaced by its own measurement. Generous
#: enough that a query, a URL or a title survives whole; small enough that a
#: page cannot.
MAX_FIELD_CHARS = 400

#: And the ceiling on the whole summary, after eliding. A tool with fifty
#: arguments is not a reason for a fifty-kilobyte row.
MAX_SUMMARY_CHARS = 4000

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
        return {str(k): digest(v, depth=depth + 1) for k, v in list(value.items())[:40]}
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


def summarise(value) -> str:
    try:
        text = json.dumps(digest(value), default=str)
    except Exception:  # noqa: BLE001 — a payload that will not serialise is
        # still an operation worth recording.
        text = "<unserialisable>"
    return text if len(text) <= MAX_SUMMARY_CHARS else text[:MAX_SUMMARY_CHARS] + "…"


@contextmanager
def record(app_state_path, *, door: str, name: str, kind: str = "", arguments=None):
    """Open a row, run the body, close the row. Never raises on its own account.

    Used as a context manager so an exception inside the body is recorded as a
    `failed` operation and then re-raised untouched: the caller's error
    handling is not this module's business.
    """
    from app.web import state

    conn = None
    op_id = 0
    started = time.monotonic()
    try:
        conn = state.connect(Path(app_state_path))
        op_id = state.open_operation(
            conn,
            door=door,
            kind=kind or kind_of(name),
            name=name,
            subject_id=str((arguments or {}).get("subject_id") or ""),
            pack_id=str((arguments or {}).get("pack_id") or ""),
            request=summarise(arguments or {}),
        )
    except Exception:  # noqa: BLE001 — see the module docstring
        conn, op_id = None, 0

    outcome = {"state": "ok", "response": "", "error": ""}
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
                )
            except Exception:  # noqa: BLE001
                pass
            finally:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
