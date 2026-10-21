"""The sweep: every case answered, its evidence fetched, its answer graded, kept.

One run is a folder with a `results.json` ledger. Each row records the case,
the answer, who answered and who graded, the evidence the grader saw, the
grader's reasoning and the failure classes. The ledger is rewritten (atomically)
after every row, so a run that is interrupted keeps what it finished, and it is
scrubbed on the way out: no key, token or e-mail address reaches the disk.

The ledger is the input of the report and of the before/after comparison, which
read it and never call an agent again.
"""

import hashlib
import json
import random
import subprocess
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from app.searchbench.metrics import wilson
from app.tuning import cases as cases_mod
from app.tuning import evidence, failures, grade
from app.tuning.scrub import scrub, scrub_obj

SCHEMA = 1


def engine_info(repo: Path | None = None) -> dict:
    """Which engine this was: the app's version and the checkout's commit.

    The commit is what makes a before and an after distinguishable when the
    version did not move. Absent git, the version alone is recorded.
    """
    from app.version import app_version

    root = repo or Path(__file__).resolve().parent
    info: dict = {"version": app_version(), "git_sha": "", "dirty": None}
    try:
        info["git_sha"] = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True,
            timeout=5, check=True).stdout.strip()
        info["dirty"] = bool(subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"], cwd=root,
            capture_output=True, text=True, timeout=5, check=True).stdout.strip())
    except Exception:  # noqa: BLE001 - no git is not an error, only less provenance
        pass
    return info


def protocol_hash() -> str:
    """Which grading rules this was. A different hash is a different grader."""
    rules = json.dumps([grade.PROTOCOL, grade.GRADER_SYSTEM, grade.FACT_CREDIT_MIN,
                        grade.CLAIMS_SUPPORTED_MIN, grade.MAX_CLAIMS], sort_keys=True)
    return hashlib.sha256(rules.encode()).hexdigest()[:16]


def _row(case: dict, rep: int, answer, pages: list[dict], links: dict, grading: dict,
         grader_ref, grader_usage: dict, error: str) -> dict:
    classes = failures.classify_row(
        error or answer.error, answer.text, grading, asked_question=answer.asked_question,
        expected_action=case.get("expected_action") or "")
    accepted = grading.get("accepted")
    status = ("error" if (error or answer.error) and not answer.text.strip()
              else "ungraded" if accepted is None
              else "accepted" if accepted else "rejected")
    return {
        "case": case["id"], "rep": rep, "source": case.get("source", ""),
        "category": case.get("category", ""), "complexity": case.get("complexity", ""),
        "question": case["question"], "status": status, "accepted": accepted,
        "answer": {"text": answer.text, "asked_question": answer.asked_question,
                   "read_urls": answer.read_urls, "error": error or answer.error,
                   "verification": answer.verification},
        "answered_by": {**answer.agent, "search_provider": answer.search_provider},
        "graded_by": grader_ref.public(),
        "evidence": [evidence.excerpt(page) for page in pages],
        "grading": grading, "failures": classes, "primary_failure": failures.primary(classes),
        "seconds": answer.seconds, "tokens": answer.tokens, "usd": answer.usd,
        "grader_usage": grader_usage, "trace": answer.log,
    }


def summarise(rows: list[dict]) -> dict:
    """The run in numbers: the pass rate with its interval, and why the rest failed."""
    graded = [row for row in rows if row["accepted"] is not None or row["status"] == "error"]
    accepted = sum(row["accepted"] is True for row in graded)
    scored = [row for row in rows if (row["grading"].get("fact_credit") is not None)]
    claims = sum(row["grading"].get("claims_total", 0) for row in rows)
    supported = sum(row["grading"].get("claims_supported", 0) for row in rows)
    links = [row["grading"].get("links") or {} for row in rows]
    usd = [row["usd"] for row in rows]
    counts = failures.tally(rows)
    return {
        "attempts": len(rows), "graded": len(graded), "accepted": accepted,
        "pass_rate": accepted / len(graded) if graded else None,
        "pass_ci95": wilson(accepted, len(graded)),
        "ungraded": sum(row["status"] == "ungraded" for row in rows),
        "fact_credit": (sum(row["grading"]["fact_credit"] for row in scored) / len(scored)
                        if scored else None),
        "claims_supported_share": supported / claims if claims else None,
        "links_total": sum(one.get("total", 0) for one in links),
        "links_open": sum(one.get("open", 0) for one in links),
        "links_invented": sum(len(one.get("invented", [])) for one in links),
        "mean_seconds": (sum(row["seconds"] for row in rows) / len(rows)) if rows else None,
        "spent_usd": sum(value for value in usd if value is not None),
        "spend_complete": bool(rows) and all(value is not None for value in usd),
        "failure_classes": counts, "commonest_failure": failures.commonest(counts),
        "by_source": {source: {"attempts": len(group),
                               "accepted": sum(row["accepted"] is True for row in group)}
                      for source in sorted({row["source"] for row in rows})
                      for group in [[row for row in rows if row["source"] == source]]},
    }


def run_tuning(cases: list[dict], answerer, grader, *, fetch: Callable[[str], object],
               folder: Path, label: str = "", reps: int = 1, seed: int = 42,
               preference: dict | None = None, engine: dict | None = None,
               on_row: Callable[[dict], None] | None = None) -> dict:
    """Answer and grade every case, `reps` times, and keep the ledger."""
    cases_mod.validate(cases)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    jobs = [(case, rep) for case in cases for rep in range(1, max(1, reps) + 1)]
    random.Random(seed).shuffle(jobs)
    document: dict = {
        "schema_version": SCHEMA, "kind": "tuning", "label": label,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "engine": engine if engine is not None else engine_info(),
        "protocol": {"grading": grade.PROTOCOL, "hash": protocol_hash()},
        "case_set": {"sha256": cases_mod.fingerprint(cases), "count": len(cases),
                     "sources": {source: sum(one.get("source") == source for one in cases)
                                 for source in sorted({one.get("source", "") for one in cases})}},
        "config": {"reps": max(1, reps), "seed": seed},
        "answered_by": preference or {}, "graded_by": grader.ref.public(),
        "cases": [{key: one.get(key) for key in ("id", "source", "question", "category", "complexity",
                                                 "criteria", "expected_action", "primary_domains",
                                                 "primary_min")} for one in cases],
        "rows": [], "summary": {},
    }
    for case, rep in jobs:
        error = ""
        try:
            answer = answerer.answer(case)
        except Exception as exc:  # noqa: BLE001 - a case that breaks the answerer is a row
            from app.tuning.answer import Answer

            answer, error = Answer(), f"{type(exc).__name__}: {exc}"
        # Scrubbed before anything else sees it: the grader is another provider's
        # model, and a key an answer happened to echo must not be sent on to it.
        answer.text, answer.log = scrub(answer.text), scrub_obj(answer.log)
        pages = (evidence.collect(evidence.urls_in(answer.text), answer.read_urls, fetch,
                                  question=case["question"]) if answer.text.strip() else [])
        links = evidence.links_summary(pages)
        before = grader.agent.usage() if hasattr(grader, "agent") else {}
        started = time.monotonic()
        grading = grader.grade(case, answer, pages, links)
        after = grader.agent.usage() if hasattr(grader, "agent") else {}
        spent = {key: (after[key] - before[key]) if after.get(key) is not None and before.get(key) is not None
                 else None for key in ("tokens", "usd")}
        spent["seconds"] = round(time.monotonic() - started, 2)
        row = _row(case, rep, answer, pages, links, grading, grader.ref, spent, error)
        document["rows"].append(row)
        document["summary"] = summarise(document["rows"])
        save(document, folder)
        if on_row is not None:
            on_row(row)
    return document


def save(document: dict, folder: Path) -> Path:
    """Write `results.json` scrubbed, replacing the old one atomically."""
    folder = Path(folder)
    temporary = folder / "results.next.json"
    temporary.write_text(json.dumps(scrub_obj(document), ensure_ascii=False, indent=1), encoding="utf-8")
    temporary.replace(folder / "results.json")
    return folder / "results.json"


def load(folder: Path) -> dict:
    path = Path(folder)
    path = path / "results.json" if path.is_dir() else path
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("kind") != "tuning":
        raise ValueError(f"{path} is not a tuning ledger")
    return document
