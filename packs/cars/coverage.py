"""coverage.py — cars-pack catalog coverage report over YAML only. No DB, no network.

The cars catalog (`packs/cars/data/**/*.yaml`) can contain silent holes: part
stubs with zero claims, fitment rows pointing at part_ids that don't exist,
orphan parts no variant ever references, or an automatic-transmission variant
with no real gearbox part behind it. Nothing surfaced these before this tool
existed. This is the recurrence guard for that whole class of bug (backlog B7,
CLAUDE.md generalization principle: "patch the car, ship the mechanism").

It lives in the pack, not the engine: every finding kind below is a statement
about *car* catalog shape (fitment axes, gearbox technology, diesel emissions),
so it moved here with the data in Phase 6 rather than staying in `ops/`.

Reads:
    packs/cars/data/variants/*.yaml — variant rows (id, transmission, transmission_code, ...)
    packs/cars/data/fitment/*.yaml  — fitment rows (variant_id + one part_id per axis,
                                    e.g. engine_family, transmission_code, electrical_code,
                                    body_code)
    packs/cars/data/parts/<type>/*.yaml — part rows (part_id, part_type, claims: [...])

Reports six finding kinds, all catalog-derived (no hardcoded make/model/code
list — see CLAUDE.md's scalability principle):
    missing_part            — a fitment row's part_id has no part YAML anywhere
                               under packs/cars/data/parts/
    zero_claim_part         — a part YAML whose claims list is empty, or whose
                               claims are all in a status the pack does not
                               export (see servable_statuses() below)
    orphan_part             — a part YAML that no fitment row references
    auto_variant_no_tx_part — a variant whose transmission field indicates an
                               automatic/automated technology but whose
                               transmission_code references no transmission-
                               type part
    variant_no_emissions    — a diesel variant with no emissions value (B11):
                               SCR claims can't ground deterministically, so
                               the gap must be visible — never a quiet wrong
                               value. Fail-open is fine; silence is not.
    draft_variant           — a variant row still carrying `draft: true`: not
                               built into the pack, so listings for it no_match.
                               Its power/year figures must come from automatic
                               derivation, never a human hand-fill (G5).

The pseudo-code "manual" is skipped everywhere it appears as a fitment row's
transmission placeholder — manual gearboxes deliberately have no part file.

Part axes are derived from the `*_family` / `*_code` field-naming convention
fitment rows already follow (engine_family, transmission_code, electrical_code,
body_code, ...) — a new axis is covered the moment a fitment row carries it,
no code change needed here.

Usage:
    python -m packs.cars.coverage
    python -m packs.cars.coverage --strict     # exit 1 if any finding (CI)
    python -m packs.cars.coverage --data-dir /path/to/catalog-root
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

PACK_ROOT = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = PACK_ROOT / "data"
MANIFEST_PATH = PACK_ROOT / "pack.toml"

# Pseudo part-code a fitment row may use as a transmission placeholder that
# deliberately has no part file. Imported from packs.cars.pipeline.catalog.registry,
# which is pure pathlib+yaml — so this read-only tool still takes on no DB
# dependency, and the constant has one definition instead of four.
from packs.cars.pipeline.catalog.registry import PSEUDO_PART_CODES  # noqa: E402


@lru_cache(maxsize=4)
def servable_statuses(manifest_path: Path = MANIFEST_PATH) -> tuple[str, ...]:
    """Statuses the pack builder actually exports, read off `pack.toml`.

    `[status_confidence]` is the single authority on what a status is worth:
    `build.py` skips any claim whose confidence is <= 0 (`draft`, `rejected`).
    Deriving the list here instead of re-hardcoding the old resolver's
    `SERVABLE_STATUSES` tuple means retuning the table cannot leave the
    coverage report reporting on a different notion of "servable" than the
    builder uses — the class of drift CLAUDE.md's scalability principle is about.
    """
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    table = manifest.get("status_confidence") or {}
    return tuple(sorted(k for k, v in table.items() if float(v) > 0))

@dataclass(frozen=True)
class Finding:
    kind: str      # missing_part | zero_claim_part | orphan_part |
                   # auto_variant_no_tx_part | variant_no_emissions
    subject: str   # part_id or variant_id, whichever this finding is keyed on
    message: str
    # part_id/axis are what the B19 auto-remediation loop consumes: which part
    # to re-research, and which axis (== part type vocabulary:
    # engine|transmission|electrical|body|cooling — the fitment axis vocabulary) it belongs to. None when the finding isn't part-driven.
    part_id: str | None = None
    axis: str | None = None


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)

    def has_findings(self) -> bool:
        return bool(self.findings)

    def grouped(self) -> dict[str, list[Finding]]:
        out: dict[str, list[Finding]] = defaultdict(list)
        for f in self.findings:
            out[f.kind].append(f)
        return out

    def render(self) -> str:
        if not self.findings:
            return "Catalog coverage: OK — no findings."
        lines = [f"Catalog coverage: {len(self.findings)} finding(s)"]
        for kind, items in sorted(self.grouped().items()):
            lines.append(f"\n{kind} ({len(items)}):")
            for it in sorted(items, key=lambda fl: fl.subject):
                lines.append(f"  - {it.subject}: {it.message}")
        return "\n".join(lines)


def _part_axis_refs(fitment_row: dict) -> dict[str, str]:
    """{axis: part_id} for a fitment row's *_code/*_family fields.

    e.g. {"engine_family": "eng1", "transmission_code": "tc1"} -> collapses to
    the axis name each field is for ("engine", "transmission", ...) so it can
    be matched against a part's own `part_type`.
    """
    refs: dict[str, str] = {}
    for k, v in fitment_row.items():
        if not isinstance(v, str) or not v:
            continue
        if k.endswith("_family"):
            refs[k[: -len("_family")]] = v
        elif k.endswith("_code"):
            refs[k[: -len("_code")]] = v
    return refs


def _load_parts(parts_dir: Path) -> dict[str, dict]:
    parts: dict[str, dict] = {}
    if not parts_dir.exists():
        return parts
    for path in sorted(parts_dir.rglob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        part_id = data.get("part_id")
        if part_id:
            parts[part_id] = data
    return parts


def _load_rows(directory: Path) -> list[dict]:
    rows: list[dict] = []
    if not directory.exists():
        return rows
    for path in sorted(directory.glob("*.yaml")):
        rows.extend(yaml.safe_load(path.read_text(encoding="utf-8")) or [])
    return rows


def build_report(variants_dir: Path, fitment_dir: Path, parts_dir: Path) -> Report:
    """Build the coverage report from the three YAML directories directly.

    No DB, no network — pure YAML-in, Report-out, so it's cheap to run in CI
    and easy to unit test with tmp-dir fixtures.
    """
    statuses = servable_statuses()
    parts = _load_parts(parts_dir)
    fitment_rows = _load_rows(fitment_dir)
    variant_rows = _load_rows(variants_dir)

    findings: list[Finding] = []
    referenced_part_ids: set[str] = set()

    # (a) missing_part — and collect every real part_id a fitment row wires up,
    # for the orphan_part check below.
    for row in fitment_rows:
        vid = row.get("variant_id", "?")
        for axis, part_id in _part_axis_refs(row).items():
            if part_id in PSEUDO_PART_CODES:
                continue
            referenced_part_ids.add(part_id)
            if part_id not in parts:
                findings.append(Finding(
                    "missing_part", part_id,
                    f"variant {vid!r} references {axis} part_id {part_id!r} — "
                    f"no part YAML found under packs/cars/data/parts/",
                    part_id=part_id, axis=axis,
                ))

    # (b) zero_claim_part — empty claims list, or claims but none servable.
    for part_id, data in sorted(parts.items()):
        part_type = data.get("part_type")
        claims = data.get("claims") or []
        if not claims:
            findings.append(Finding(
                "zero_claim_part", part_id, "part YAML has 0 claims",
                part_id=part_id, axis=part_type,
            ))
            continue
        servable = [c for c in claims if c.get("status") in statuses]
        if not servable:
            findings.append(Finding(
                "zero_claim_part", part_id,
                f"{len(claims)} claim(s), none in a servable status {statuses}",
                part_id=part_id, axis=part_type,
            ))

    # (c) orphan_part — a part file no fitment row references.
    for part_id in sorted(parts):
        if part_id not in referenced_part_ids:
            findings.append(Finding(
                "orphan_part", part_id, "no fitment row references this part",
                part_id=part_id, axis=parts[part_id].get("part_type"),
            ))

    # (d) auto_variant_no_tx_part — automatic-tech variant, no real tx part.
    # The catalog's "transmission" field is a closed two-value vocabulary
    # today (manual/automatic — see packs/cars/pipeline/catalog/write_variants.py), but
    # rather than hardcode "automatic" we treat anything that isn't the
    # "manual" placeholder as an automatic/automated technology, so a future
    # value (e.g. "cvt", "semi-automatic") is covered without a code change.
    for row in variant_rows:
        vid = row.get("id", "?")
        tx = row.get("transmission")
        if not tx or tx in PSEUDO_PART_CODES:
            continue  # manual tech, or unset — nothing to check
        tx_code = row.get("transmission_code")
        part = parts.get(tx_code) if tx_code else None
        if (
            not tx_code
            or tx_code in PSEUDO_PART_CODES
            or part is None
            or part.get("part_type") != "transmission"
        ):
            findings.append(Finding(
                "auto_variant_no_tx_part", vid,
                f"transmission={tx!r} but transmission_code={tx_code!r} "
                f"references no transmission-type part",
                part_id=(tx_code or None) if tx_code not in PSEUDO_PART_CODES else None,
                axis="transmission",
            ))

    # (e) variant_no_emissions — diesel variant without an emissions value
    # (B11). Fail-open (no SCR grounding) is safe; a *quiet* gap is not — an
    # AdBlue claim would then ground to this variant through the SCR gate's
    # unknown-side pass. Visibility is the point; remediation (evidence-derived
    # values) is the B19 loop's job, not a human sign-off.
    for row in variant_rows:
        vid = row.get("id", "?")
        if (row.get("fuel") or "").lower() != "diesel":
            continue
        if not row.get("emissions"):
            findings.append(Finding(
                "variant_no_emissions", vid,
                "diesel variant has no emissions value — fail-open, no SCR "
                "grounding; the gap must stay visible until evidence-derived "
                "values exist (B11)",
            ))

    # (f) draft_variant — scaffolded row not synced to serving. Discovery
    # scaffolds these with engine/transmission/fuel only; the power/year
    # figures it can't reliably get from Wikipedia were historically left for
    # a human to hand-fill — a step G5 bans. The row stays visible here (and
    # no_match listings for it surface in the demand miner) until automatic
    # derivation exists; silence would be a quiet coverage hole.
    for row in variant_rows:
        if row.get("draft"):
            findings.append(Finding(
                "draft_variant", row.get("id", "?"),
                "draft row — not synced; power/year figures must be derived "
                "automatically, never hand-filled (G5)",
            ))

    return Report(findings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--data-dir", type=Path, default=DEFAULT_DATA_DIR,
        help="catalog root containing variants/, fitment/, parts/ "
             "(default: packs/cars/data)",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="exit 1 if any finding (for CI); without it, always exits 0",
    )
    args = parser.parse_args(argv)

    report = build_report(
        args.data_dir / "variants",
        args.data_dir / "fitment",
        args.data_dir / "parts",
    )
    print(report.render())

    if args.strict and report.has_findings():
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
