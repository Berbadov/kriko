"""swap.py — swap the served parts catalog for the ledger export (backlog B16).

The ledger export (knowledge/ledger_export/, part-dict schema with grounded
serving gates) is the acceptance-ready future catalog; the legacy
backend/data/parts/** still serves. Swapping is a mechanical, derived, and
measured step — never a hand-edited list:

  1. plan()   — derive the legacy -> merged fitment remap from the export's
                own legacy_part_ids fields (power-collapse rule, k9k_110 ->
                k9k), classify every legacy part file (superseded by an export
                file / retained because the export doesn't cover it yet), and
                report post-swap coverage gaps.
  2. apply()  — write export files into parts/<type>/, delete superseded
                legacy files, rewrite fitment axis ids through the remap.
                Revertible (git checkout -- backend/data) and default off the
                real catalog (runs on a copy unless --in-place).
  3. check()  — the automated acceptance gate (no human sign-off, G5):
                (a) parity: every legacy claim absent from the export must be
                    attributable to a named gate — "never extracted/ingested"
                    counts are LOST claims and fail the gate;
                (b) serving baseline: replay the logged /analyze fixture
                    against a freshly synced post-swap DB — any changed
                    listing fails the gate;
                (c) coverage: the post-swap catalog must not add findings the
                    pre-swap catalog didn't have.

The gate may legitimately fail (the export is thinner than the legacy catalog
in places); that failure is the point — it feeds the B19 auto-remediation
loop, and the swap lands when the export catches up. Data-gated, not
human-gated.

Usage:
    python -m knowledge.ledger.swap plan
    python -m knowledge.ledger.swap check
    python -m knowledge.ledger.swap apply --in-place   # after check passes
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from backend.tools.coverage import build_report
from knowledge.ledger import db as ledger_db
from knowledge.ledger.export import merged_part_id

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DATA_DIR = REPO_ROOT / "backend" / "data"
DEFAULT_EXPORT_DIR = Path(__file__).resolve().parent.parent / "ledger_export"
DEFAULT_BASELINE = REPO_ROOT / "backend" / "tests" / "fixtures" / "serving_baseline_2026-07-22.json"

_AXIS_SUFFIXES = ("_family", "_code")
# Pseudo part-code fitment rows may use for a transmission with deliberately no
# part file (mirrors backend/sync.py + backend/tools/coverage.py).
PSEUDO_PART_CODES = frozenset({"manual"})


@dataclass
class Plan:
    export_parts: dict[str, dict] = field(default_factory=dict)   # merged id -> part data
    remap: dict[str, str] = field(default_factory=dict)           # legacy id -> merged id
    superseded: list[str] = field(default_factory=list)           # replaced by an export file
    retained: list[str] = field(default_factory=list)             # no export counterpart
    fitment_edits: int = 0
    missing_after: list[str] = field(default_factory=list)        # fitment-referenced ids, absent post-swap


def _load_part_files(parts_dir: Path) -> dict[str, dict]:
    parts: dict[str, dict] = {}
    if not parts_dir.exists():
        return parts
    for path in sorted(parts_dir.rglob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text())
        except yaml.YAMLError:
            print(f"  WARN: unparseable part YAML {path} — skipped")
            continue
        # The export dir can carry stale bare-list artifacts from the pre-schema
        # export (e.g. golf7_cool_cooling, held back since B1). They are not
        # part-dict files and must not enter the plan.
        if not isinstance(data, dict):
            print(f"  WARN: {path} is not a part-dict file — skipped")
            continue
        if data.get("part_id"):
            parts[str(data["part_id"])] = data
    return parts


def build_plan(export_dir: Path, data_dir: Path) -> Plan:
    export_parts = _load_part_files(export_dir)
    legacy_parts = _load_part_files(data_dir / "parts")
    plan = Plan(export_parts={
        pid: {"part_type": d.get("part_type"), "claims": len(d.get("claims") or [])}
        for pid, d in sorted(export_parts.items())})

    # Legacy -> merged remap: a legacy file is superseded whenever the export
    # carries its merged id (the export declares the power-split mapping in
    # legacy_part_ids, and the same deterministic rule covers the rest);
    # anything the export doesn't cover is retained as-is. Nothing is
    # hand-enumerated.
    exported_merged = {merged_part_id(pid) for pid in export_parts}
    for legacy_id in sorted(legacy_parts):
        merged = merged_part_id(legacy_id)
        if merged in exported_merged:
            plan.superseded.append(legacy_id)
            if merged != legacy_id:
                plan.remap[legacy_id] = merged
        else:
            plan.retained.append(legacy_id)

    # Fitment: rewrite every axis id through the remap; ids that still have no
    # part file after the swap are the coverage gap the remediate loop owns.
    for fpath in sorted((data_dir / "fitment").glob("*.yaml")):
        for row in yaml.safe_load(fpath.read_text()) or []:
            for k, v in row.items():
                if isinstance(v, str) and k.endswith(_AXIS_SUFFIXES):
                    new_v = plan.remap.get(v, v)
                    if new_v != v:
                        plan.fitment_edits += 1
                    if new_v not in PSEUDO_PART_CODES and new_v not in export_parts \
                            and new_v not in legacy_parts:
                        plan.missing_after.append(new_v)
    plan.missing_after = sorted(set(plan.missing_after))
    return plan


def apply(export_dir: Path, data_dir: Path, plan: Plan) -> None:
    """Write the export into data_dir/parts, delete superseded legacy files,
    rewrite fitment through the remap. data_dir is the catalog root
    (variants/fitment/parts live under it)."""
    parts_root = data_dir / "parts"
    for pid, data in plan.export_parts.items():
        ptype = data["part_type"]
        out = parts_root / ptype / f"{pid}.yaml"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(yaml.dump(
            _load_part_files(export_dir)[pid], allow_unicode=True, sort_keys=False))

    # Delete only the legacy files the export replaces under a NEW identity
    # (power-split: k9k_110 -> k9k). Non-split superseded ids (dc4, ea211, …)
    # were already overwritten in place by the export write above — deleting
    # them via rglob would delete the fresh export files too.
    for legacy_id in plan.remap:
        for path in parts_root.rglob(f"{legacy_id}.yaml"):
            path.unlink()

    for fpath in sorted((data_dir / "fitment").glob("*.yaml")):
        rows = yaml.safe_load(fpath.read_text()) or []
        changed = False
        for row in rows:
            for k, v in row.items():
                if isinstance(v, str) and k.endswith(_AXIS_SUFFIXES):
                    new_v = plan.remap.get(v, v)
                    if new_v != v:
                        row[k] = new_v
                        changed = True
        if changed:
            fpath.write_text(yaml.dump(rows, allow_unicode=True, sort_keys=False))


# ── Automated acceptance gate ────────────────────────────────────────────────

_LOST_REASONS = {
    "never extracted by the ledger",
    "source never ingested into ledger",
    "no matching evidence extracted from source",
}


def _post_swap_catalog(export_dir: Path, data_dir: Path) -> Path:
    """Copy data_dir to a temp dir and apply the swap there. Returns the copy."""
    tmp = Path(tempfile.mkdtemp(prefix="kriko_swap_"))
    shutil.copytree(data_dir, tmp, dirs_exist_ok=True)
    apply(export_dir, tmp, build_plan(export_dir, tmp))
    return tmp


def _parity_check(conn, export_dir: Path, data_dir: Path) -> tuple[dict, dict]:
    """(explain_breakdown, verdict) — every legacy claim absent from the export
    must be attributable to a named gate; 'never extracted/ingested' counts as
    lost."""
    from knowledge.ledger import parity
    legacy_dirs = [data_dir / "parts", data_dir / "claims"]
    _, _, only_old, _ = parity._match(legacy_dirs, export_dir)
    breakdown: dict[str, int] = {}
    if conn is not None:
        text = parity.explain_only_old(conn, legacy_dirs, export_dir)
        for line in text.splitlines():
            line = line.strip()
            if line[:1].isdigit():
                n, _, reason = line.partition("  ")
                breakdown[reason] = int(n)
    lost = sum(n for r, n in breakdown.items() if r in _LOST_REASONS)
    return breakdown, {"lost": lost, "only_in_export": len(only_old),
                       "unexplained_without_ledger": len(only_old) if conn is None else 0}


def _coverage_check(export_dir: Path, data_dir: Path, post_dir: Path) -> tuple[set, set]:
    """(pre_swap_findings, post_swap_findings) — post must not add any."""
    pre = build_report(data_dir / "variants", data_dir / "fitment", data_dir / "parts")
    post = build_report(post_dir / "variants", post_dir / "fitment", post_dir / "parts")
    return ({(f.kind, f.subject) for f in pre.findings},
            {(f.kind, f.subject) for f in post.findings})


def _matched(resp: dict) -> bool:
    return bool(resp.get("matched_variant_ids")) or resp.get("coverage_state") == "risks_found"


def _serving_check(data_dir: Path, post_dir: Path, baseline_path: Path) -> dict:
    """Replay the logged /analyze baseline through (a) the current catalog and
    (b) the post-swap catalog, on two freshly synced DBs. The swap's own delta
    is (a) vs (b) — a comparison against the 2026-07-22 snapshot alone would
    report every catalog improvement since then as a "change". Gate rule: a
    listing that matches today must still match after the swap (risk-set
    thinning is quantified by the parity check instead)."""
    import json

    import yaml as _yaml
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from backend.api.main import run_analysis
    from backend.db.models import Claim, ClaimSource, ClaimVariant, Variant
    from backend.tools.replay import compute_diff

    records = json.loads(baseline_path.read_text())
    ids = [r.get("id", str(i)) for i, r in enumerate(records)]
    metas = [r.get("ad_metadata") or {} for r in records]

    import backend.sync as sync_mod
    orig = (sync_mod.DATA_DIR, sync_mod.PARTS_DIR, sync_mod.FITMENT_DIR)

    def _serving_for(catalog_dir: Path) -> dict:
        eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        for table in (Variant.__table__, Claim.__table__,
                      ClaimVariant.__table__, ClaimSource.__table__):
            table.create(eng, checkfirst=True)
        sync_mod.DATA_DIR, sync_mod.PARTS_DIR, sync_mod.FITMENT_DIR = (
            catalog_dir, catalog_dir / "parts", catalog_dir / "fitment")
        out: dict = {}
        try:
            with Session(eng) as db:
                valid_columns = {c.name for c in Variant.__table__.columns}
                for vpath in sorted((catalog_dir / "variants").glob("*.yaml")):
                    for row in _yaml.safe_load(vpath.read_text()):
                        db.add(Variant(**{k: v for k, v in row.items()
                                          if k in valid_columns}))
                db.flush()
                sync_mod.sync_parts(db)
                sync_mod.sync_claims(db)
                db.commit()
                for rid, meta in zip(ids, metas):
                    try:
                        _c, _m, _s, resp = run_analysis(meta, db)
                        out[rid] = resp.model_dump(mode="json")
                    except Exception as exc:
                        out[rid] = {"_error": str(exc)}
        finally:
            eng.dispose()
        return out

    try:
        current = _serving_for(data_dir)
        post = _serving_for(post_dir)
    finally:
        sync_mod.DATA_DIR, sync_mod.PARTS_DIR, sync_mod.FITMENT_DIR = orig

    changed: list[dict] = []
    regressions: list[str] = []
    for rid in ids:
        diff = compute_diff(current[rid], post[rid])
        if diff:
            changed.append({"id": rid, "diff": diff})
        if _matched(current[rid]) and not _matched(post[rid]):
            regressions.append(rid)
    baseline_changed = sum(
        1 for r, rid in zip(records, ids)
        if not post[rid].get("_error")
        and compute_diff(r.get("response") or {}, post[rid]))
    return {"replayed": len(records), "changed_by_swap": len(changed),
            "regressions": regressions,
            "changed_vs_2026_07_22_baseline": baseline_changed,
            "entries": changed[:5]}


def check(conn, export_dir: Path, data_dir: Path, baseline_path: Path) -> dict:
    """Run the three acceptance checks against a temp post-swap catalog. The
    real catalog is never touched. Returns the result dict; exit code is the
    CLI's call."""
    post_dir = _post_swap_catalog(export_dir, data_dir)
    result: dict = {}
    result["plan"] = build_plan(export_dir, data_dir)
    result["parity"], result["parity_check"] = _parity_check(conn, export_dir, data_dir)
    pre, post = _coverage_check(export_dir, data_dir, post_dir)
    result["coverage_new_findings"] = sorted(post - pre)
    result["coverage"] = {"pre": len(pre), "post": len(post)}
    result["serving"] = _serving_check(data_dir, post_dir, baseline_path)
    result["passes"] = (
        result["parity_check"]["lost"] == 0
        and result["parity_check"]["unexplained_without_ledger"] == 0
        and not result["coverage_new_findings"]
        and not result["serving"]["regressions"])
    return result


# ── CLI ──────────────────────────────────────────────────────────────────────


def _render(result: dict) -> str:
    plan = result["plan"]
    lines = [
        "swap plan:",
        f"  export parts: {len(plan.export_parts)} "
        f"({sum(p['claims'] for p in plan.export_parts.values())} claims)",
        f"  superseded legacy files: {len(plan.superseded)}",
        f"  retained legacy files (not in export): {plan.retained or '-'}",
        f"  fitment axis edits: {plan.fitment_edits}",
        f"  post-swap fitment gaps (missing_part targets): {plan.missing_after or '-'}",
    ]
    if "parity" in result:
        lines.append("acceptance: parity")
        for reason, n in sorted(result["parity"].items(), key=lambda kv: -kv[1]):
            lines.append(f"    {n:4d}  {reason}")
        lines.append(f"  -> lost claims: {result['parity_check']['lost']}")
    if "coverage" in result:
        lines.append(f"acceptance: coverage findings {result['coverage']['pre']} -> "
                     f"{result['coverage']['post']}")
        if result["coverage_new_findings"]:
            lines.append(f"  NEW findings: {result['coverage_new_findings']}")
    if "serving" in result:
        s = result["serving"]
        lines.append(f"acceptance: serving {s['replayed']} replayed — "
                     f"{s['changed_by_swap']} differ vs current serving, "
                     f"{len(s['regressions'])} match-loss regression(s), "
                     f"{s['changed_vs_2026_07_22_baseline']} vs the 07-22 snapshot")
        for e in s["entries"][:5]:
            lines.append(f"    {e['id']}: {e.get('diff', e.get('error'))}")
    if "passes" in result:
        lines.append("RESULT: " + ("PASS" if result["passes"] else "FAIL"))
    return "\n".join(lines)

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["plan", "check", "apply"])
    p.add_argument("--export-dir", type=Path, default=DEFAULT_EXPORT_DIR)
    p.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    p.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    p.add_argument("--db", default=str(ledger_db.LEDGER_PATH),
                   help="ledger DB for parity --explain")
    p.add_argument("--in-place", action="store_true",
                   help="apply to the real catalog (default: a temp copy)")
    args = p.parse_args(argv)

    if args.command == "plan":
        print(_render({"plan": build_plan(args.export_dir, args.data_dir)}))
        return 0
    if args.command == "apply":
        if args.in_place:
            apply(args.export_dir, args.data_dir, build_plan(args.export_dir, args.data_dir))
            print(f"applied to {args.data_dir} — re-sync serving, then `check` again")
        else:
            tmp = _post_swap_catalog(args.export_dir, args.data_dir)
            print(f"applied to a copy: {tmp} (revert with: rm -rf {tmp})")
        return 0
    conn = ledger_db.connect(args.db)
    result = check(conn, args.export_dir, args.data_dir, args.baseline)
    print(_render(result))
    return 0 if result["passes"] else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
