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
from pathlib import Path

from app.findings import accept_findings
from app.web.jobs import Progress
from kriko.research import get_researcher, plan_task
from kriko.store import packstore
from kriko.store.db import connect


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

    out = Path(params.get("out") or Path("dist") / f"{root.name}.kpack")
    out.parent.mkdir(parents=True, exist_ok=True)

    progress.set(0.1, f"building {root.name}")
    stats = None
    if (root / "build.py").exists():
        progress.log(f"{root.name} ships its own builder")
        module = importlib.import_module(f"packs.{root.name}.build")
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


HANDLERS = {"research": research, "pack_build": pack_build}
