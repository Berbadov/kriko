"""validate_part_yaml.py — validate all backend/data/parts/**/*.yaml files.

Checks structure, required fields, and that claim_keys are unique across all parts.
Used as a CI gate before sync.

Usage:
    python -m knowledge.parts.validate_part_yaml
    python -m knowledge.parts.validate_part_yaml backend/data/parts/engine/k9k.yaml
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

PARTS_DIR = Path(__file__).parent.parent.parent / "backend" / "data" / "parts"

REQUIRED_PART_FIELDS = {"part_id", "part_type", "display_name", "manufacturer", "claims"}
VALID_PART_TYPES = {"engine", "transmission", "turbo", "fuel_intake", "exhaust", "cooling", "electrical", "body"}
REQUIRED_CLAIM_FIELDS = {"claim_key", "title", "kind", "domain", "severity", "status", "rationale", "inspection_advice"}
VALID_KINDS = {"known_issue", "maintenance", "recall"}
VALID_SEVERITIES = {"high", "medium", "low"}
VALID_STATUSES = {"draft", "verified", "review", "held", "rejected"}


def validate_part(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        return [f"{path}: YAML parse error: {e}"]

    if not isinstance(data, dict):
        return [f"{path}: root must be a mapping, got {type(data).__name__}"]

    missing = REQUIRED_PART_FIELDS - data.keys()
    if missing:
        errors.append(f"{path}: missing required fields: {missing}")

    part_type = data.get("part_type", "")
    if part_type not in VALID_PART_TYPES:
        errors.append(f"{path}: invalid part_type {part_type!r}, must be one of {VALID_PART_TYPES}")

    part_id = data.get("part_id", "")
    if part_id != path.stem:
        errors.append(f"{path}: part_id {part_id!r} does not match filename {path.stem!r}")

    claims = data.get("claims", [])
    if not isinstance(claims, list):
        errors.append(f"{path}: 'claims' must be a list")
        return errors

    seen_keys: set[str] = set()
    for i, claim in enumerate(claims):
        loc = f"{path}[{i}]"
        if not isinstance(claim, dict):
            errors.append(f"{loc}: claim must be a mapping")
            continue

        missing_c = REQUIRED_CLAIM_FIELDS - claim.keys()
        if missing_c:
            errors.append(f"{loc}: missing fields: {missing_c}")

        key = claim.get("claim_key", "")
        if key in seen_keys:
            errors.append(f"{loc}: duplicate claim_key {key!r}")
        seen_keys.add(key)

        kind = claim.get("kind", "")
        if kind not in VALID_KINDS:
            errors.append(f"{loc}: invalid kind {kind!r}")

        sev = claim.get("severity", "")
        if sev not in VALID_SEVERITIES:
            errors.append(f"{loc}: invalid severity {sev!r}")

        status = claim.get("status", "")
        if status not in VALID_STATUSES:
            errors.append(f"{loc}: invalid status {status!r}")

        if kind == "maintenance" and not claim.get("maintenance"):
            errors.append(f"{loc}: maintenance claim missing 'maintenance' block")

        if status in ("verified", "review") and kind != "maintenance":
            sources = claim.get("sources", [])
            if not sources:
                errors.append(f"{loc}: servable non-maintenance claim has no sources")

    return errors


def validate_all(paths: list[Path]) -> int:
    all_claim_keys: dict[str, str] = {}  # key → first seen path
    total_errors = 0

    for path in sorted(paths):
        errors = validate_part(path)
        for e in errors:
            print(f"ERROR: {e}")
        total_errors += len(errors)

        # Cross-file duplicate check
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError:
            continue
        for claim in data.get("claims", []) or []:
            key = claim.get("claim_key", "")
            if not key:
                continue
            if key in all_claim_keys:
                print(f"ERROR: duplicate claim_key {key!r} in {path} and {all_claim_keys[key]}")
                total_errors += 1
            else:
                all_claim_keys[key] = str(path)

    return total_errors


def main() -> None:
    if len(sys.argv) > 1:
        paths = [Path(p) for p in sys.argv[1:]]
    else:
        paths = list(PARTS_DIR.rglob("*.yaml"))

    if not paths:
        print(f"No part YAML files found under {PARTS_DIR}")
        sys.exit(1)

    print(f"Validating {len(paths)} part YAML file(s)…")
    n_errors = validate_all(paths)

    if n_errors == 0:
        print(f"OK — all files valid.")
    else:
        print(f"\n{n_errors} error(s) found.")
        sys.exit(1)


if __name__ == "__main__":
    main()
