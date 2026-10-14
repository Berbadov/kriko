"""The task set: loaded, and checked against itself before anything runs."""

import json
from pathlib import Path

from app.providers.local_identity import fold

SUITE_FILE = Path(__file__).with_name("suite.json")


def load(only: list[str] | tuple[str, ...] = (), path: Path | None = None) -> dict:
    """The suite, in file order, narrowed to `only` when named.

    File order on purpose: the suite is versioned, and a stable order is part
    of what the version promises. An unknown task id is an error and not a
    silently smaller run, so a typo cannot turn into a pass.
    """
    suite = json.loads((path or SUITE_FILE).read_text(encoding="utf-8"))
    tasks = suite.get("tasks") or []
    if only:
        known = {one["id"] for one in tasks}
        missing = [name for name in only if name not in known]
        if missing:
            raise ValueError(f"unknown task(s): {', '.join(missing)}; "
                             f"known: {', '.join(sorted(known))}")
        tasks = [one for one in tasks if one["id"] in set(only)]
    return {**suite, "tasks": tasks}


def validate(suite: dict) -> list[str]:
    """What is wrong with the suite itself. Empty means it can be trusted.

    A key that cites a quote the page does not contain would fail every agent
    for the suite's fault. So every quote must be on its page, every cited url
    must be a page of the task, and every id must be unique.
    """
    problems: list[str] = []
    seen: set[str] = set()
    for task in suite.get("tasks") or []:
        name = task.get("id", "?")
        if name in seen:
            problems.append(f"{name}: duplicate task id")
        seen.add(name)
        pages = {page["url"]: page for page in task.get("pages") or []}
        if not task.get("product"):
            problems.append(f"{name}: no product")
        if len(pages) != len(task.get("pages") or []):
            problems.append(f"{name}: duplicate page url")
        expect = task.get("expect") or {}
        ids: set[str] = set()
        for group in ("supported", "specs"):
            for entry in expect.get(group) or []:
                label = f"{name}/{entry.get('id', '?')}"
                if entry.get("id") in ids:
                    problems.append(f"{label}: duplicate id")
                ids.add(entry.get("id"))
                page = pages.get(entry.get("url"))
                if page is None:
                    problems.append(f"{label}: cites a url that is not a page of the task")
                elif fold(entry.get("quote", "")) not in fold(page["text"]):
                    problems.append(f"{label}: quote is not on its page")
                if group == "supported" and not entry.get("terms"):
                    problems.append(f"{label}: no terms to recognise the claim by")
                if group == "specs" and not entry.get("values"):
                    problems.append(f"{label}: no values")
                if not (entry.get("say") or {}).get("default"):
                    problems.append(f"{label}: no default `say` for the scripted agents")
        for entry in expect.get("forbidden") or []:
            if not entry.get("terms") and not entry.get("urls"):
                problems.append(f"{name}/{entry.get('id', '?')}: forbidden by nothing")
            for url in entry.get("urls") or []:
                if url not in pages:
                    problems.append(f"{name}/{entry.get('id', '?')}: url not a page of the task")
        if expect.get("abstain") and expect.get("supported"):
            problems.append(f"{name}: abstains yet lists supported claims")
        marker = (expect.get("injection") or {}).get("marker")
        if marker and not any(marker in page["text"] for page in pages.values()):
            problems.append(f"{name}: the injection marker is on no page")
        if not expect.get("supported") and not expect.get("abstain") and not expect.get("specs"):
            problems.append(f"{name}: expects nothing")
    return problems
