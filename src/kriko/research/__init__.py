"""Choosing a research plane, and building a task from what a pack knows."""

import yaml

from kriko.research.agent import AgentResearcher
from kriko.research.api import ApiResearcher, BudgetExceeded
from kriko.research.base import Document, Finding, Researcher, ResearchTask

__all__ = [
    "AgentResearcher", "ApiResearcher", "BudgetExceeded",
    "Document", "Finding", "Researcher", "ResearchTask",
    "get_researcher", "plan_task",
]


def get_researcher(config: dict | None = None, **kwargs):
    """Pick a plane. The default is the one that costs nothing.

    Defaulting to `agent` is a decision, not an accident: a tool that quietly
    starts spending money because a key happened to be in the environment is a
    tool people stop trusting.
    """
    config = config or {}
    backend = (config.get("backend") or "agent").lower()
    if backend == "agent":
        return AgentResearcher()
    if backend == "api":
        return ApiResearcher(**kwargs)
    raise ValueError(f"unknown research backend {backend!r} (expected agent|api)")


def _asset(conn, pack_id: str, name: str) -> str:
    row = conn.execute(
        "SELECT content FROM pack_assets WHERE pack_id = ? AND name = ?",
        (pack_id, name)).fetchone()
    return row["content"] if row else ""


def plan_task(conn, subject_id: str, pack_id: str, *,
              budget_usd: float = 0.0, max_documents: int = 5) -> ResearchTask:
    """Assemble everything the pack knows about how to research this subject.

    Every category-specific thing the old pipeline hard-coded — the query
    templates in `search_templates.py`, the product principle inlined in
    `verdict.py` — arrives here as pack data instead.
    """
    subject = conn.execute(
        "SELECT kind, label FROM subjects WHERE subject_id = ? AND pack_id = ?",
        (subject_id, pack_id)).fetchone()
    if subject is None:
        raise KeyError(f"no subject {subject_id} in pack {pack_id}")

    identity = {
        row["key"]: row["value_text"] for row in conn.execute(
            "SELECT key, value_text FROM attributes"
            " WHERE subject_id = ? AND pack_id = ? AND is_identity = 1",
            (subject_id, pack_id))
    }

    aliases = {"attribution_safe": [], "search_only": []}
    for row in conn.execute(
            "SELECT alias, tier FROM subject_aliases"
            " WHERE subject_id = ? AND pack_id = ? ORDER BY alias",
            (subject_id, pack_id)):
        aliases.setdefault(row["tier"], []).append(row["alias"])

    templates = yaml.safe_load(_asset(conn, pack_id, "research/templates.yaml")) or []
    domains = [row["term_id"] for row in conn.execute(
        "SELECT term_id FROM terms WHERE pack_id = ? AND role = 'domain'"
        " ORDER BY term_id", (pack_id,))]

    return ResearchTask(
        subject_id=subject_id,
        subject_label=subject["label"],
        subject_kind=subject["kind"],
        pack_id=pack_id,
        identity=identity,
        search_aliases=tuple(aliases.get("search_only") or ()),
        attribution_aliases=tuple(aliases.get("attribution_safe") or ()),
        queries=tuple(templates),
        value_principle=_asset(conn, pack_id, "research/principle.md"),
        domains=tuple(domains),
        budget_usd=budget_usd,
        max_documents=max_documents,
    )
