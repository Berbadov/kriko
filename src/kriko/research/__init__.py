"""Choosing a research plane, and building a task from what a pack knows."""

import yaml

from kriko.gates import load_gates

from kriko.research.agent import AgentResearcher
from kriko.research.api import ApiResearcher, BudgetExceeded
from kriko.research.local import LocalPlane
from kriko.research.base import (
    STANDARD,
    Document,
    Fetched,
    Finding,
    Researcher,
    ResearchTask,
    Spend,
)

__all__ = [
    "AgentResearcher", "ApiResearcher", "BudgetExceeded",
    "Document",
    "Fetched", "Finding", "Researcher", "ResearchTask", "Spend", "STANDARD",
    "get_researcher", "pack_asset", "plan_task",
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
    if backend == "local":
        return LocalPlane(**kwargs)
    raise ValueError(f"unknown research backend {backend!r} (expected agent|api|local)")


def pack_asset(conn, pack_id: str, name: str) -> str:
    """One of a pack's non-tabular files, or "" if it ships none.

    Public because the pack's own words — its principle, its templates — are
    what any consumer of a pack needs; nothing outside should have to know the
    asset table's shape to read them.
    """
    row = conn.execute(
        "SELECT content FROM pack_assets WHERE pack_id = ? AND name = ?",
        (pack_id, name)).fetchone()
    return row["content"] if row else ""


def _pack_languages(conn, pack_id: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """What `[pack] languages` and `[pack] markets` say, off the installed row.

    Read from `packs.manifest_json` rather than from a new column: the whole
    `pack.toml` is already carried there verbatim, and a schema migration to
    hold a declaration the manifest already states would be a second answer to
    the same question.
    """
    row = conn.execute(
        "SELECT manifest_json FROM packs WHERE pack_id = ?", (pack_id,)
    ).fetchone()
    if row is None:
        return (), ()
    try:
        manifest = yaml.safe_load(row["manifest_json"]) or {}
    except yaml.YAMLError:
        return (), ()
    pack = manifest.get("pack") if isinstance(manifest, dict) else None
    if not isinstance(pack, dict):
        return (), ()

    def codes(value) -> tuple[str, ...]:
        if not value:
            return ()
        items = [value] if isinstance(value, str) else list(value)
        return tuple(str(item).strip() for item in items if str(item).strip())

    return codes(pack.get("languages")), codes(
        pack.get("markets") or pack.get("market")
    )


def _templates(raw, primary: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split `research/templates.yaml` into queries and their languages.

    Two shapes, because a pack that serves one language should not have to say
    so on every line:

        - "{alias} common problems"                      # the pack's primary
        - {query: "{alias} arıza şikayet", lang: "tr"}   # this one is Turkish

    A mapping with no `query` key is skipped rather than raised on: a pack is
    data from a third party, and one malformed line must not take the other
    six queries down with it.
    """
    queries: list[str] = []
    langs: list[str] = []
    for entry in raw or []:
        if isinstance(entry, str):
            queries.append(entry)
            langs.append(primary)
        elif isinstance(entry, dict):
            query = entry.get("query") or entry.get("q") or ""
            if not query:
                continue
            queries.append(str(query))
            langs.append(str(entry.get("lang") or entry.get("language") or primary))
    return tuple(queries), tuple(langs)


def plan_task(conn, subject_id: str, pack_id: str, *,
              budget_usd: float = 0.0, max_documents: int = 5) -> ResearchTask:
    """Assemble everything the pack knows about how to research this subject.

    Everything category-specific — query templates, the product principle —
    arrives here as pack data, never as engine code.
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

    aliases: dict[str, list[str]] = {
        "attribution_safe": [], "search_only": [], "search_name": []
    }
    for row in conn.execute(
            "SELECT alias, tier FROM subject_aliases"
            " WHERE subject_id = ? AND pack_id = ? ORDER BY alias",
            (subject_id, pack_id)):
        aliases.setdefault(row["tier"], []).append(row["alias"])

    languages, markets = _pack_languages(conn, pack_id)
    raw_templates = yaml.safe_load(
        pack_asset(conn, pack_id, "research/templates.yaml")) or []
    templates, template_langs = _templates(
        raw_templates, languages[0] if languages else "")
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
        search_names=tuple(aliases.get("search_name") or ()),
        attribution_aliases=tuple(aliases.get("attribution_safe") or ()),
        queries=templates,
        query_languages=template_langs,
        languages=languages,
        markets=markets,
        value_principle=pack_asset(conn, pack_id, "research/principle.md"),
        domains=tuple(domains),
        budget_usd=budget_usd,
        max_documents=max_documents,
        min_rationale_chars=load_gates(conn, pack_id).min_rationale_chars,
    )
