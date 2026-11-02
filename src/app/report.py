"""A report the reader reads, then sends themselves.

Kriko composes the text and sends nothing. The desktop window shows it, and the
reader copies it, saves it, or opens a prefilled issue in their own browser and
presses Submit there. With no button pressed, nothing leaves the machine.
"""

import platform
import re
from pathlib import Path
from urllib.parse import urlencode

from app import redaction
from app.version import app_version
from app.web import state, steps

KINDS = ("error", "suggestion")
NOTE_CHARS = 4000
STEP_LIMIT = 300
ISSUE_BODY_CHARS = 6000
TRIMMED = "\n\n(Trimmed to fit a link. The full report is on your clipboard: paste it here.)"


def draft(conn, *, kind: str, job_id: str, note: str, issues_url: str) -> dict:
    note = note.strip()[:NOTE_CHARS]
    run = _run(conn, job_id) if kind == "error" else ""
    parts = [
        ("What happened" if kind == "error" else "Suggestion", note or "(nothing written)"),
        ("Run", run) if run else None,
        ("This machine", _machine()),
    ]
    if run:
        parts.append(("Log, redacted", steps.export_text(conn, job_id=job_id, limit=STEP_LIMIT)["text"]))
    text = _scrub("\n\n".join(f"## {name}\n{body}" for name, body in filter(None, parts)).strip() + "\n")
    title = _title(kind, note, conn, job_id)
    body = text if len(text) <= ISSUE_BODY_CHARS else text[:ISSUE_BODY_CHARS - len(TRIMMED)] + TRIMMED
    return {
        "title": title,
        "text": text,
        "filename": f"kriko-{kind}-report.txt",
        "url": f"{issues_url}?{urlencode({'title': title, 'body': body})}",
    }


def _run(conn, job_id: str) -> str:
    job = state.get_job(conn, job_id) if job_id else None
    if job is None:
        return ""
    summary = next((one for one in steps.list_jobs(conn, limit=200) if one["job_id"] == job_id), {})
    facts = [("job", f"{job['kind']} ({job['state']})"), ("label", summary.get("label")),
             ("message", job.get("message")), ("started", job.get("started_at")),
             ("took", f"{summary['duration_ms'] / 1000:.1f} s" if summary.get("duration_ms") else None),
             ("errors in the log", summary.get("errors"))]
    return "\n".join(f"{name}: {value}" for name, value in facts if value not in (None, ""))


def _machine() -> str:
    try:
        from app.providers import harness
        agents = ", ".join(one.id for one in harness.available()) or "none found"
    except Exception:  # noqa: BLE001 — a report is worth sending without this line
        agents = "unknown"
    return f"Kriko {app_version()}\n{platform.system()} {platform.release()}\nagents found: {agents}"


def _title(kind: str, note: str, conn, job_id: str) -> str:
    first = re.sub(r"\s+", " ", note.splitlines()[0] if note else "").strip()[:70]
    job = state.get_job(conn, job_id) if job_id else None
    what = first or (f"{job['kind']} {job['state']}" if job else "")
    return f"[{'problem' if kind == 'error' else 'suggestion'}] {what}".strip()


def _scrub(text: str) -> str:
    text = redaction.redact_text(text)
    home = str(Path.home())
    return text.replace(home, "~") if len(home) > 3 else text
