"""The two operations that actually grow the knowledge base.

Before this module both were terminal-only, which is the specific thing G6's
delivery constraint forbids. Neither handler invents any logic: `research`
drives `kriko.research`'s `Researcher` protocol and hands what comes back to
`app.findings.accept_findings` — the same acceptance path MCP uses, so a claim's
provenance does not depend on which door it came in. `pack_build` runs the same
builder `app.cli`'s `kriko pack build` runs.

A handler is `(settings, params, progress) -> dict`. It reports through
`progress` only: printing to stdout would be invisible in the browser, which is
the whole point of the jobs layer.
"""

import importlib
from datetime import UTC, datetime
from pathlib import Path

from app import packsource

from app.findings import accept_findings, log_submission
from app.web.jobs import Progress
from kriko.pack import updates
from kriko.research import get_researcher, plan_task
from kriko.store import packstore
from kriko.store.db import connect


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _subject_pack(conn, subject_id: str) -> str:
    row = conn.execute(
        "SELECT pack_id FROM subjects WHERE subject_id = ?", (subject_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"no subject {subject_id} is installed")
    return row["pack_id"]


def research(settings, params: dict, progress: Progress) -> dict:
    """Research one subject with whichever plane the caller is paying for.

    The default plane is `agent`, whose `gather` returns nothing by design —
    the searching is done by a coding-agent harness whose subscription is
    already paid for. So on the default plane this job's real output is the
    brief, and that is not a degraded result: it is the $0 path, and refusing
    to run it because it cannot also fetch would push the cheapest way to grow
    a pack back into the terminal.
    """
    subject_id = params.get("subject_id") or ""
    if not subject_id:
        raise ValueError("subject_id is required")

    conn = connect(settings.store_path)
    try:
        pack_id = params.get("pack_id") or _subject_pack(conn, subject_id)
        task = plan_task(
            conn,
            subject_id,
            pack_id,
            budget_usd=float(params.get("budget_usd") or 0.0),
            max_documents=int(params.get("max_documents") or 5),
        )
        progress.set(0.1, f"planning {task.subject_label}")
        for query in task.rendered_queries():
            progress.log(f"query: {query}")

        researcher = get_researcher({"backend": params.get("backend") or "agent"})
        brief = researcher.brief(task)
        progress.set(0.2, f"{researcher.name} plane ({researcher.cost_basis})")
        progress.check()

        documents = researcher.gather(task)
        progress.log(f"gathered {len(documents)} document(s)")

        findings: list[dict] = []
        for index, document in enumerate(documents, start=1):
            progress.check()
            progress.set(
                0.2 + 0.6 * index / max(1, len(documents)),
                f"reading {document.site_or_channel or document.url}",
            )
            for finding in researcher.extract(task, document):
                findings.append(
                    {
                        "title": finding.title,
                        "body": finding.body,
                        "advice": finding.advice,
                        "domain": finding.domain,
                        "severity": finding.severity,
                        "quote": finding.quote,
                        "source_url": finding.source_url,
                        "stance": finding.stance,
                        "component": finding.component,
                        # The document text is what makes the grounding check
                        # possible. Without it every finding is refused, which
                        # is the correct failure — "trust me" is not an
                        # evidence model.
                        "document_text": document.text,
                    }
                )

        progress.check()
        verdicts = {"accepted": [], "rejected": []}
        if findings:
            progress.set(0.85, f"checking {len(findings)} finding(s)")
            verdicts = accept_findings(conn, subject_id, pack_id, findings)
            conn.commit()
            # The refusals are the point of the ledger, so it is written even
            # when nothing was kept — a batch that lost everything is the one
            # an author most needs to be able to read afterwards.
            log_submission(
                settings.app_state_path,
                door="job",
                subject_id=subject_id,
                pack_id=pack_id,
                verdicts=verdicts,
            )
        for item in verdicts.get("rejected", []):
            progress.log(f"refused “{item['title']}”: {item['reason']}")
        for item in verdicts.get("accepted", []):
            progress.log(f"kept “{item['title']}” as {item['claim_id']}")

        progress.set(1.0, f"{len(verdicts.get('accepted', []))} claim(s) kept")
        return {
            "subject": task.subject_label,
            "pack_id": pack_id,
            "plane": researcher.name,
            "cost_basis": researcher.cost_basis,
            "queries": list(task.rendered_queries()),
            "brief": brief,
            "documents": len(documents),
            **verdicts,
        }
    finally:
        conn.close()


def pack_build(settings, params: dict, progress: Progress) -> dict:
    """Build a pack directory into a `.kpack`, and install it unless told not to.

    Same path and same rules as `kriko pack build`: a pack shipping its own
    `build.py` gets to use it (pointing the generic builder at such a pack
    "succeeds" and produces a pack with nothing in it), and an artifact with no
    subjects and no claims is refused rather than installed — a pack that can
    answer nothing is a failed build, not a quiet one.
    """
    root = Path(params.get("root") or "")
    if not root.name:
        raise ValueError("root is required")
    if not root.is_dir():
        candidate = settings.packs_dir / root.name
        if not candidate.is_dir():
            raise ValueError(f"not a pack directory: {root}")
        root = candidate

    from kriko.pack.build import build as generic_build
    from kriko.pack.build import digest_of

    out = Path(params.get("out") or settings.dist_dir / f"{root.name}.kpack")
    out.parent.mkdir(parents=True, exist_ok=True)

    progress.set(0.1, f"building {root.name}")
    stats = None
    if (root / "build.py").exists():
        progress.log(f"{root.name} ships its own builder")
        try:
            module = importlib.import_module(f"packs.{root.name}.build")
        except ModuleNotFoundError as exc:
            # The frozen desktop sidecar bundles the engine, not the repo's
            # packs. A pack whose builder is Python can only be built where
            # that Python is importable, and saying so beats a traceback about
            # a module nobody asked for.
            raise ValueError(
                f"{root.name} builds itself with Python (packs/{root.name}/"
                f"build.py), which this build of Kriko cannot import "
                f"({exc}). Build it from a source checkout with "
                f"`python -m app.cli build {root}`, then install the .kpack "
                f"here."
            ) from exc
        result = module.build(out)
        if isinstance(result, tuple):
            out, report = result
            if isinstance(report, dict):
                stats = report.get("stats", report)
        else:
            out = result
    else:
        generic_build(root, out)

    progress.check()
    out = Path(out)
    digest = digest_of(out)
    progress.set(0.6, f"built {out.name} ({digest[:12]})")

    counts = {}
    artifact = connect(out)
    try:
        for table in ("subjects", "claims", "evidence"):
            counts[table] = artifact.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
    finally:
        artifact.close()
    progress.log(", ".join(f"{value} {name}" for name, value in counts.items()))
    for key, value in sorted((stats or {}).items()):
        progress.log(f"{key}: {value}")

    if not counts["subjects"] and not counts["claims"]:
        raise ValueError(
            f"{out} has no subjects and no claims — it cannot answer anything, "
            "so it was not installed"
        )

    installed = None
    if params.get("install", True):
        progress.check()
        progress.set(0.8, "installing")
        store = connect(settings.store_path)
        try:
            installed = packstore.install(store, out)
            store.commit()
        finally:
            store.close()
        progress.log(f"installed revision {installed}")

    progress.set(1.0, f"{root.name} built" + (" and installed" if installed else ""))
    return {
        "root": str(root),
        "artifact": str(out),
        "digest": digest,
        "counts": counts,
        "stats": stats or {},
        "installed": installed,
    }


def _installed_rows(conn):
    return conn.execute(
        "SELECT pack_id, name, version, content_digest, origin_url FROM packs"
        " ORDER BY pack_id"
    ).fetchall()


def check_updates(settings, index_url: str = "") -> dict:
    """Compare what is installed against what the index offers.

    Synchronous and cheap — one small JSON fetch — so it is a request rather
    than a job. Network failure is reported as a value, not raised: "we could
    not reach the index" is a legitimate answer to "is anything newer", and a
    500 would make the Packs screen look broken when only the network is.
    """
    url = index_url or settings.pack_index_url
    conn = connect(settings.store_path)
    try:
        rows = _installed_rows(conn)
    finally:
        conn.close()

    try:
        candidates = packsource.fetch_index(url)
    except Exception as exc:  # noqa: BLE001 — unreachable is an answer, not a crash
        return {
            "index_url": url,
            "error": f"{type(exc).__name__}: {exc}",
            "checked_at": _now(),
            "packs": [
                {
                    "pack_id": row["pack_id"],
                    "name": row["name"],
                    "installed_version": row["version"],
                    "state": updates.UNKNOWN,
                    "reason": "the pack index could not be reached",
                }
                for row in rows
            ],
        }

    decisions = updates.plan(rows, candidates)
    known = {row["pack_id"] for row in rows}
    names = {row["pack_id"]: row["name"] for row in rows}
    payload = [
        {
            "pack_id": d.pack_id,
            "name": names.get(d.pack_id, d.pack_id),
            "installed_version": d.installed_version,
            "offered_version": d.offered_version,
            "state": d.state,
            "reason": d.reason,
            "url": d.candidate.url if d.candidate else "",
            "size": d.candidate.size if d.candidate else 0,
            "published_at": d.candidate.published_at if d.candidate else "",
        }
        for d in decisions
    ]
    # Packs the index offers that are not installed yet. Shown because an empty
    # store is the normal state of a fresh install: the first "update" a reader
    # wants is the one that gives them any knowledge at all.
    payload += [
        {
            "pack_id": c.pack_id,
            "name": c.name or c.pack_id,
            "installed_version": "",
            "offered_version": c.version,
            "state": "not_installed",
            "reason": "available, not installed",
            "url": c.url,
            "size": c.size,
            "published_at": c.published_at,
        }
        for c in candidates
        if c.pack_id not in known
    ]
    return {"index_url": url, "error": None, "checked_at": _now(), "packs": payload}


def pack_update(settings, params: dict, progress: Progress) -> dict:
    """Download and install every pack the index has something newer for.

    Goes through `packstore.install` like every other door: an updated pack is
    not a special kind of pack, and a second install path is a second place for
    the immutability rule to be forgotten.
    """
    only = params.get("pack_id") or ""
    index_url = params.get("index_url") or settings.pack_index_url
    progress.set(0.05, f"reading {index_url}")
    candidates = packsource.fetch_index(index_url)
    progress.log(f"index offers {len(candidates)} pack(s)")

    conn = connect(settings.store_path)
    try:
        rows = _installed_rows(conn)
    finally:
        conn.close()

    known = {row["pack_id"] for row in rows}
    wanted = [d for d in updates.plan(rows, candidates) if d.actionable]
    wanted += [
        updates.Decision(c.pack_id, updates.AVAILABLE, "not installed",
                         "", c.version, c)
        for c in candidates
        if c.pack_id not in known
    ]
    if only:
        wanted = [d for d in wanted if d.pack_id == only]
        if not wanted:
            raise ValueError(
                f"the index offers nothing newer for {only!r}"
                if only in known
                else f"the index does not carry a pack called {only!r}"
            )
    if not wanted:
        progress.set(1.0, "everything is up to date")
        return {"index_url": index_url, "updated": [], "skipped": len(rows)}

    into = Path(settings.store_path).parent / "downloads"
    updated = []
    for position, decision in enumerate(wanted, start=1):
        progress.check()
        share = (position - 1) / len(wanted)
        candidate = decision.candidate
        progress.set(0.1 + 0.8 * share, f"downloading {candidate.pack_id} {candidate.version}")
        path = packsource.download(
            candidate,
            into,
            lambda read, total: progress.set(
                0.1 + 0.8 * (share + (read / total if total else 0) / len(wanted)),
                f"downloading {candidate.pack_id} {read // 1024} KiB",
            ),
        )
        progress.check()
        progress.log(f"installing {path.name}")
        store = connect(settings.store_path)
        try:
            pack_id = packstore.install(store, path)
            store.commit()
        finally:
            store.close()
        # The file is the transport, not the record: the store holds the
        # revision, so keeping downloads around would only grow ~/.kriko.
        path.unlink(missing_ok=True)
        updated.append(
            {
                "pack_id": pack_id,
                "version": candidate.version,
                "from": decision.installed_version,
            }
        )
        progress.log(f"{pack_id} is now {candidate.version}")

    progress.set(1.0, f"updated {len(updated)} pack(s)")
    return {"index_url": index_url, "updated": updated, "skipped": len(rows) - len(updated)}


HANDLERS = {
    "research": research,
    "pack_build": pack_build,
    "pack_update": pack_update,
}
