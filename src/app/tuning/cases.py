"""The questions a tuning run asks.

Two sources, one shape. The benchmark corpus (`app.searchbench/products.json`)
brings questions whose required facts were checked against primary sources.
The reader's own saved chats bring the questions they really asked, and those
have no rubric: the grader then judges what it can judge without one (claims
against the fetched pages, links that open, the product asked about) and says
that required facts were not scored.

**Chats are opt-in, and proposing sends nothing anywhere.** `propose_from_chats`
reads `app.sqlite` locally, takes only the conversations the reader names,
scrubs credentials and e-mail addresses from what it takes, and returns plain
dicts. No agent is called and no network is touched; the reader reads the file
it is written to, deletes what they would not want asked, and only then runs
it. Nothing in this module spends anything.

A case is a dict, so a case file can be edited by hand:

    id, question, source ("bench" | "chat" | "file"), category, complexity,
    criteria [{id, fact, critical}], primary_domains, primary_min,
    expected_action ("" | "clarify"), references, history [{role, text}]
"""

import hashlib
import json
import sqlite3
from pathlib import Path

from app.tuning.scrub import scrub

BENCH_CORPUS = Path(__file__).resolve().parent.parent / "searchbench" / "products.json"

#: A saved question outside these bounds is not a case: too short to mean
#: anything, too long to be one question.
MIN_QUESTION, MAX_QUESTION = 12, 1200
#: The history a follow-up case carries, so the answerer has what the reader had.
MAX_HISTORY = 6


def bench_cases() -> list[dict]:
    """The benchmark corpus as tuning cases (frozen: the file is never edited here)."""
    cases = json.loads(BENCH_CORPUS.read_text(encoding="utf-8-sig"))
    return [{**case, "source": "bench"} for case in cases]


def load_file(path: Path) -> list[dict]:
    """Cases from a JSON file: a list, or an object holding `cases`."""
    found = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    cases = found.get("cases") if isinstance(found, dict) else found
    if not isinstance(cases, list):
        raise ValueError(f"{path}: expected a list of cases or an object with `cases`")
    return [{"source": "file", **one} for one in cases if isinstance(one, dict)]


def validate(cases: list[dict]) -> list[dict]:
    """The cases, or a ValueError naming everything wrong with them."""
    problems: list[str] = []
    if not cases:
        problems.append("no cases")
    seen: set[str] = set()
    for case in cases:
        name = str(case.get("id") or "").strip()
        if not name:
            problems.append("a case has no id")
        elif name in seen:
            problems.append(f"{name}: duplicate id")
        seen.add(name)
        if not isinstance(case.get("question"), str) or not case["question"].strip():
            problems.append(f"{name or '?'}: no question")
        criteria = case.get("criteria") or []
        if not isinstance(criteria, list):
            problems.append(f"{name}: criteria must be a list")
            continue
        ids = [one.get("id") for one in criteria if isinstance(one, dict)]
        if len(ids) != len(criteria) or any(not one for one in ids) or len(set(ids)) != len(ids):
            problems.append(f"{name}: every criterion needs its own id")
        elif any(not str(one.get("fact") or "").strip() for one in criteria):
            problems.append(f"{name}: every criterion needs its fact")
    if problems:
        raise ValueError("; ".join(problems))
    return cases


def fingerprint(cases: list[dict]) -> str:
    """Which set of questions this was. Two runs are only paired when it matches.

    Questions and rubrics only: a note or a reference link may change without
    changing what is being asked.
    """
    frozen = [{"id": one["id"], "question": one["question"],
               "criteria": one.get("criteria") or [],
               "expected_action": one.get("expected_action") or "",
               "history": one.get("history") or []}
              for one in sorted(cases, key=lambda case: case["id"])]
    return hashlib.sha256(json.dumps(frozen, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# ── from the reader's own chats ─────────────────────────────────────────────

def saved_threads(conn: sqlite3.Connection) -> list[dict]:
    """The conversations the reader could opt in: id, name, and how many
    questions each holds. Reads titles and counts only; no message text."""
    rows = conn.execute(
        "SELECT t.thread_id, t.title, t.updated_at,"
        " (SELECT COUNT(*) FROM chat_messages m WHERE m.thread_id = t.thread_id AND m.role = 'reader')"
        " AS questions FROM chat_threads t ORDER BY t.updated_at DESC, t.rowid DESC").fetchall()
    return [{"thread_id": row["thread_id"], "title": scrub(row["title"] or ""),
             "questions": row["questions"], "updated_at": row["updated_at"]} for row in rows]


def propose_from_chats(conn: sqlite3.Connection, thread_ids: list[str], *,
                       follow_ups: bool = False, limit: int = 50) -> list[dict]:
    """Cases proposed from the conversations the reader opted in. Local only.

    Only the named threads are read; naming none proposes nothing, because a
    default that reads every chat would not be an opt-in. By default only the
    first question of a thread is proposed, since a later one depends on the
    conversation before it; `follow_ups` takes those too, carrying the
    preceding messages as the history the answerer will be given.

    What is taken is scrubbed (credentials, e-mail addresses). The cases have
    no rubric: they say so (`criteria: []`), and the report does not score
    required facts for them.
    """
    cases: list[dict] = []
    seen: set[str] = set()
    for thread_id in dict.fromkeys(thread_ids):
        rows = conn.execute(
            "SELECT role, text FROM chat_messages WHERE thread_id = ? ORDER BY rowid",
            (thread_id,)).fetchall()
        history: list[dict] = []
        position = 0  # the reader's questions in this thread so far
        for row in rows:
            text = scrub(" ".join(str(row["text"] or "").split()))
            if row["role"] == "reader":
                usable = MIN_QUESTION <= len(text) <= MAX_QUESTION and text.casefold() not in seen
                if usable and (position == 0 or follow_ups):
                    seen.add(text.casefold())
                    cases.append({
                        "id": f"chat-{thread_id[:8]}-{position + 1}", "source": "chat",
                        "question": text, "category": "", "complexity": "chat",
                        "criteria": [], "primary_domains": [], "primary_min": 0,
                        "expected_action": "", "references": [],
                        "history": history[-MAX_HISTORY:] if position else [],
                        "proposed_from": thread_id})
                    if len(cases) >= limit:
                        return cases
                position += 1
            history.append({"role": row["role"], "text": text[:MAX_QUESTION]})
    return cases
