"""CLI: mine no_match analyses into an onboarding demand queue (backlog B10).

logs/analyses.jsonl records every /analyze request (backend/observability.py).
Many are match.method == "no_match" — real buyers on cars Kriko doesn't cover
(Audi Q2, BMW 3 Series, VW CC…) or covered cars falling through a catalog hole
(a 2024 Megane no_matched because the petrol year window ends earlier). Nobody
aggregates these today, so onboarding priorities are guesswork. This reads the
log directly (same no-DB, no-browser read path as backend/tools/analyses.py) and
groups the no_match requests by make/model into a demand table.

    python -m backend.tools.demand
    python -m backend.tools.demand --log /path/to/analyses.jsonl --limit 10

Each group is classified so the table separates the two actionable signals from
noise:

    not_onboarded — make/model isn't in the catalog at all (onboard a new model)
    catalog_gap   — make/model IS onboarded but no variant matched (fill a
                    year/fuel hole in an existing model)
    missing_fields — the scrape lacked required fields, so no match was even
                    attempted (a data-quality signal, not demand)

Catalog membership is derived from backend/data/variants/*.yaml via
normalize.py's helpers — no hardcoded car names (CLAUDE.md scalability
principle), so a newly onboarded model shifts from not_onboarded to catalog_gap
automatically. Read-only: this never writes the log.
"""

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

from backend import config
from backend.core.normalize import (
    _catalog_makes_models,
    normalize_fuel,
    normalize_make,
    normalize_model,
)

_UNSCRAPED = "(unscraped)"


@dataclass
class DemandGroup:
    """One (make, model) demand row — the tool's public result unit."""

    make: str
    model: str
    count: int
    reason: str
    years: list
    fuels: list
    transmissions: list
    example_url: str | None = None


@dataclass
class _Acc:
    """Mutable per-group accumulator (sets dedupe, converted to sorted lists)."""

    make: str
    model: str
    present: bool
    onboarded: bool
    count: int = 0
    years: set = field(default_factory=set)
    fuels: set = field(default_factory=set)
    transmissions: set = field(default_factory=set)
    has_real_attempt: bool = False
    example_url: str | None = None


def _display(raw) -> str | None:
    """Whitespace-stripped raw display form, or None if absent/blank."""
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _is_onboarded(make_slug: str | None, model_slug: str | None) -> bool:
    """True when both catalog-normalized slugs are already in the variants catalog.

    Uses the same catalog-derived sets normalize.py compares against for its
    soft "not yet onboarded" signal, so this needs no separate car registry and
    stays correct as new models are onboarded.
    """
    if not make_slug or not model_slug:
        return False
    makes, models = _catalog_makes_models()
    return make_slug in makes and model_slug in models


def _classify(acc: _Acc) -> str:
    """Reason for a group. Precedence favours the actionable onboarding signal:

    A known make+model we don't cover is `not_onboarded` even if some of its
    records also lacked fields — the takeaway is "onboard this model". Only when
    make/model are genuinely unknown (unscraped) or a covered model's records all
    failed before a match could be attempted does it fall to `missing_fields`.
    """
    if acc.present and not acc.onboarded:
        return "not_onboarded"
    if acc.onboarded and acc.has_real_attempt:
        return "catalog_gap"
    return "missing_fields"


def _read_records(path: Path) -> tuple[list[dict], int]:
    """Parse a JSONL log, skipping (and counting) malformed lines. Never raises.

    "Malformed" covers both JSON syntax errors and well-formed JSON that
    parses to something other than an object (e.g. a bare `42`, `null`, a
    quoted string, or a JSON array) — every record shape mine() understands
    is a dict, so a non-dict parse is just as unusable as invalid JSON and
    must not be handed to callers that assume `.get()` works.
    """
    records: list[dict] = []
    skipped = 0
    if not path.exists():
        return records, skipped
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except ValueError:
                skipped += 1
                continue
            if not isinstance(parsed, dict):
                skipped += 1
                continue
            records.append(parsed)
    return records, skipped


def mine(path: Path, limit: int | None = None) -> tuple[list[DemandGroup], int]:
    """Aggregate no-variant records in `path` into demand groups.

    Returns (groups sorted by count desc then make/model, skipped_line_count).
    `limit` caps the returned rows to the top N.
    """
    records, skipped = _read_records(path)

    accs: dict[tuple[str | None, str | None], _Acc] = {}
    for rec in records:
        match = rec.get("match")
        if not match:
            # match is None when /analyze raised before matching ran at all
            # (backend/api/main.py's error path) — a server fault, not a
            # "this car isn't covered" signal, so it isn't demand.
            continue
        if match.get("variant_ids"):
            # A variant WAS identified (exact or ambiguous) — the selection
            # criterion is "produced no variants", not the literal string
            # "no_match", so any future zero-variant method (e.g. matcher.py's
            # "inconsistent_listing") is picked up here with no code change.
            continue

        meta = rec.get("ad_metadata") or {}
        make_disp = _display(meta.get("make"))
        model_disp = _display(meta.get("model"))
        # Group by the catalog-aware normalized slug, not a raw lowercase
        # string — "VW" and "Volkswagen" must collapse into one group (they
        # are literally both present in the real log for the same car), and
        # normalize.py is the single place that knows about that alias.
        make_slug = normalize_make(meta.get("make"))
        model_slug = normalize_model(meta.get("model"))
        key = (make_slug, model_slug)

        acc = accs.get(key)
        if acc is None:
            present = make_slug is not None and model_slug is not None
            acc = _Acc(
                make=make_disp or _UNSCRAPED,
                model=model_disp or _UNSCRAPED,
                present=present,
                onboarded=present and _is_onboarded(make_slug, model_slug),
            )
            accs[key] = acc

        acc.count += 1
        if meta.get("year") is not None:
            acc.years.add(meta["year"])
        if meta.get("fuel_type"):
            acc.fuels.add(str(meta["fuel_type"]))
        if meta.get("transmission"):
            acc.transmissions.add(str(meta["transmission"]))
        # A "real attempt" means this record's own ad_metadata had every field
        # matcher.py's hard filter requires before it even looks at the
        # catalog (backend/core/matcher.py: `not make or not model or not fuel
        # or not year`). Derived straight from the metadata — NOT by sniffing
        # match.notes for matcher.py's "Missing required fields" wording — so
        # this stays correct even if that free-text prose changes or a
        # record's notes disagree with its own metadata.
        fuel_slug = normalize_fuel(meta.get("fuel_type"))
        if make_slug and model_slug and fuel_slug and meta.get("year"):
            acc.has_real_attempt = True
        if acc.example_url is None:
            url = rec.get("listing_url") or meta.get("url")
            if url:
                acc.example_url = str(url)

    groups = [
        DemandGroup(
            make=acc.make,
            model=acc.model,
            count=acc.count,
            reason=_classify(acc),
            years=sorted(acc.years, key=str),
            fuels=sorted(acc.fuels),
            transmissions=sorted(acc.transmissions),
            example_url=acc.example_url,
        )
        for acc in accs.values()
    ]
    groups.sort(key=lambda g: (-g.count, g.make.lower(), g.model.lower()))
    if limit is not None:
        groups = groups[:limit]
    return groups, skipped


def format_table(groups: list[DemandGroup], skipped: int) -> str:
    """Render demand groups as a plain-text table (analyses.py print style)."""
    if not groups:
        line = "No no_match analyses found."
        if skipped:
            line += f" ({skipped} malformed line(s) skipped)"
        return line

    mk_w = max(len("MAKE"), *(len(g.make) for g in groups))
    md_w = max(len("MODEL"), *(len(g.model) for g in groups))
    rs_w = max(len("REASON"), *(len(g.reason) for g in groups))
    tx_w = max(len("TRANSMISSIONS"), *(len(", ".join(g.transmissions)) for g in groups))

    def _row(make, model, count, reason, years, fuels, tx, url):
        return (f"{make:<{mk_w}}  {model:<{md_w}}  {count:>5}  {reason:<{rs_w}}  "
                f"{years:<26}  {fuels:<20}  {tx:<{tx_w}}  {url}")

    lines = [_row("MAKE", "MODEL", "COUNT", "REASON", "YEARS", "FUELS",
                  "TRANSMISSIONS", "EXAMPLE_URL")]
    for g in groups:
        lines.append(_row(
            g.make, g.model, g.count, g.reason,
            ", ".join(str(y) for y in g.years),
            ", ".join(g.fuels),
            ", ".join(g.transmissions),
            g.example_url or "-",
        ))

    total = sum(g.count for g in groups)
    footer = f"\n{len(groups)} group(s), {total} no_match request(s)"
    if skipped:
        footer += f" — {skipped} malformed line(s) skipped"
    lines.append(footer)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--log", type=Path, default=config.ANALYSES_LOG_PATH,
        help="Path to analyses.jsonl (default: <repo>/logs/analyses.jsonl).",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Show only the top N demand groups (default: all).",
    )
    args = parser.parse_args(argv)

    groups, skipped = mine(args.log, limit=args.limit)
    print(format_table(groups, skipped))


if __name__ == "__main__":
    main()
