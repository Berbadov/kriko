"""Catalog doctor — find (and fix) identity damage in the variant catalog.

`identity.py` stops bad rows at the *write* path. This is the other half: the
catalog already on disk was written by earlier paths (a hand-edited table, an
agent run before the gate existed), so something has to inspect what is there
and repair it — for every car, automatically, with no per-model patch
(CLAUDE.md generalization principle: when a problem shows up on one car, ship
the mechanism that catches it on all of them).

Five findings, all decidable from the YAML alone:

  noncanonical_code      a part code stored in non-catalog form ("7-speed DSG")
  invalid_code           a code that names a description or a shared technology
                         family instead of a physical unit — claims attributed
                         to it would contaminate sibling parts
  trim_shaped_id         a variant id naming a showroom trim, not a powertrain
  powertrain_duplicate   two rows describing one powertrain (mergeable)
  unresolvable_overlap   two rows a listing can never tell apart, and merging
                         them would be wrong (different gearboxes) — reported,
                         never auto-fixed, because the fix is research
  fitment_orphan         a fitment row for a variant that no longer exists

`diagnose()` is the CI gate (`packs/cars/pipeline/tests/test_catalog_doctor.py`),
`repair()` is the unattended fix. Run:

    python -m packs.cars.pipeline.catalog.doctor            # report
    python -m packs.cars.pipeline.catalog.doctor --fix      # repair in place
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from packs.cars.pipeline.catalog import identity
from packs.cars.pipeline.catalog.write_variants import build_fitment_rows

from packs.cars.pipeline.paths import REPO_ROOT
DATA_DIR = REPO_ROOT / "packs" / "cars" / "data"

CODE_FIELDS = ("engine_family", "transmission_code", "electrical_code",
               "body_code")


@dataclass
class Finding:
    kind: str
    model_key: str
    subject: str
    message: str
    fixable: bool = True


@dataclass
class Repair:
    findings: list[Finding] = field(default_factory=list)
    rewritten: list[str] = field(default_factory=list)
    renames: dict[str, str] = field(default_factory=dict)


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or []
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def _normalize_row(row: dict) -> tuple[dict, list[str]]:
    """Canonicalize a row's codes; return (row, list of what changed)."""
    out, changes = dict(row), []
    for f in CODE_FIELDS:
        raw = out.get(f)
        if raw in (None, ""):
            continue
        canon = identity.canonical_code(raw)
        if out.get("transmission") == "manual" and f == "transmission_code" \
                and identity.is_manualish(canon):
            canon = identity.MANUAL_CODE
        if canon != raw:
            changes.append(f"{f}: {raw!r} -> {canon!r}")
            out[f] = canon
    return out, changes


def diagnose(data_dir: Path | None = None) -> list[Finding]:
    """Everything wrong with the catalog's identity layer, per model."""
    data_dir = data_dir or DATA_DIR
    findings: list[Finding] = []

    for path in sorted((data_dir / "variants").glob("*.yaml")):
        key = path.stem
        rows = _load(path)

        for row in rows:
            rid = row.get("id", "?")
            normalized, changes = _normalize_row(row)
            for change in changes:
                findings.append(Finding(
                    "noncanonical_code", key, rid,
                    f"{rid}: code not in catalog form — {change}"))
            for f in ("engine_family", "transmission_code"):
                if not normalized.get(f):
                    continue
                for err in identity.code_errors(f, normalized[f],
                                                normalized.get("transmission")):
                    findings.append(Finding("invalid_code", key, rid, f"{rid}: {err}",
                                            fixable=False))
            token_errors = _trim_shaped(key, normalized)
            findings.extend(token_errors)

        merged, notes = identity.collapse_duplicates(
            [_normalize_row(r)[0] for r in rows])
        for note in notes:
            findings.append(Finding("powertrain_duplicate", key, key, note))

        for line in identity.find_overlaps(merged):
            findings.append(Finding("unresolvable_overlap", key, key, line,
                                    fixable=False))

        live = {r["id"] for r in merged}
        for frow in _load(data_dir / "fitment" / f"{key}.yaml"):
            vid = frow.get("variant_id")
            if vid and vid not in live:
                findings.append(Finding(
                    "fitment_orphan", key, str(vid),
                    f"fitment row {vid!r} has no variant — it serves nothing"))

    return findings


def _trim_shaped(model_key: str, row: dict) -> list[Finding]:
    """Ids that name a showroom trim rather than the powertrain they describe."""
    rid = str(row.get("id") or "")
    family = identity.canonical_code(row.get("engine_family"))
    token = family.split("_")[0] if family else ""
    token = "".join(c for c in token if c.isalnum())
    if not rid or not token or token in rid.lower().replace("-", "_"):
        return []
    return [Finding(
        "trim_shaped_id", model_key, rid,
        f"{rid}: id names a trim, not the powertrain (engine family {family!r}) "
        f"— suggested {identity.canonical_variant_id(model_key, row)!r}")]


def repair(data_dir: Path | None = None, dry_run: bool = False) -> Repair:
    """Fix what a rule can fix; leave what needs research reported.

    Order matters: normalize codes, then rename trim-shaped ids (so the merge
    keys off canonical values), then collapse duplicates, then re-project
    fitment from the surviving rows. Fitment is fully rewritten rather than
    appended to, because a rename or a merge leaves orphans behind and an
    orphan fitment row silently serves nothing.
    """
    data_dir = data_dir or DATA_DIR
    result = Repair()

    for path in sorted((data_dir / "variants").glob("*.yaml")):
        key = path.stem
        rows = _load(path)
        if not rows:
            continue

        changed = False
        fixed: list[dict] = []
        for row in rows:
            new_row, changes = _normalize_row(row)
            changed = changed or bool(changes)
            # A code nobody could resolve to a real unit fails open: the row is
            # marked draft (sync skips it, coverage reports it) rather than
            # serving claims attributed to a part that will never exist.
            if any(identity.code_errors(f, new_row.get(f) or "",
                                        new_row.get("transmission"))
                   for f in ("engine_family", "transmission_code")
                   if new_row.get(f)) and not new_row.get("draft"):
                new_row["draft"] = True
                changed = True
            for finding in _trim_shaped(key, new_row):
                canonical = identity.canonical_variant_id(key, new_row)
                result.renames[new_row["id"]] = canonical
                result.findings.append(finding)
                new_row["id"] = canonical
                changed = True
            fixed.append(new_row)

        merged, notes = identity.collapse_duplicates(fixed)
        for note in notes:
            result.findings.append(Finding("powertrain_duplicate", key, key, note))
        changed = changed or bool(notes)

        # A rename can collide two rows onto one id (two trims of one
        # powertrain that the merge did not catch because a figure differs).
        # Dedupe by id, keeping the first — the merge already widened windows.
        seen: dict[str, dict] = {}
        for row in merged:
            seen.setdefault(row["id"], row)
        final = list(seen.values())
        changed = changed or len(final) != len(rows)

        for line in identity.find_overlaps(final):
            result.findings.append(Finding("unresolvable_overlap", key, key, line,
                                           fixable=False))

        # Fitment is NOT a pure projection of the variant row. The B16 catalog
        # swap remapped it to the merged part files (a variant still says
        # `engine_family: h5f_100`; its fitment row points at the researched
        # `h5f` part). Re-projecting from the variant would silently undo that
        # remap and point the row at a part file that no longer exists — so
        # existing rows are preserved verbatim; only renames, orphans, and
        # genuinely missing rows are touched.
        fitment_path = data_dir / "fitment" / f"{key}.yaml"
        fitment_rows = _load(fitment_path)
        live_ids = {r["id"] for r in final}
        kept = []
        for frow in fitment_rows:
            old_id = str(frow.get("variant_id") or "")
            vid = result.renames.get(old_id, old_id)
            if vid not in live_ids or any(k.get("variant_id") == vid for k in kept):
                continue                      # orphan, or a merged-away duplicate
            kept.append({**frow, "variant_id": vid})
        have = {r["variant_id"] for r in kept}
        kept.extend(r for r in build_fitment_rows(final)
                    if r["variant_id"] not in have)
        want_fitment = kept
        fitment_changed = fitment_rows != want_fitment

        if not (changed or fitment_changed) or dry_run:
            continue

        header = "\n".join(l for l in path.read_text().splitlines()
                           if l.startswith("#"))
        path.write_text((header + "\n\n" if header else "")
                        + yaml.dump(final, allow_unicode=True, sort_keys=False))
        if fitment_changed:
            fitment_path.write_text(
                yaml.dump(want_fitment, allow_unicode=True, sort_keys=False))
        result.rewritten.append(key)

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", action="store_true", help="repair in place")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args()

    if args.fix:
        res = repair(args.data_dir)
        for f in res.findings:
            print(f"[{f.kind}] {f.model_key}: {f.message}")
        print(f"\nrewritten: {', '.join(res.rewritten) or 'nothing'}")
        if res.renames:
            print("renames:")
            for old, new in res.renames.items():
                print(f"  {old} -> {new}")
        remaining = [f for f in diagnose(args.data_dir) if not f.fixable]
        for f in remaining:
            print(f"NEEDS RESEARCH [{f.kind}] {f.model_key}: {f.message}")
        return 1 if remaining else 0

    findings = diagnose(args.data_dir)
    for f in findings:
        print(f"[{f.kind}] {f.model_key}: {f.message}")
    print(f"\n{len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
