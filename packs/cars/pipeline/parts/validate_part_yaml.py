"""validate_part_yaml.py — validate all packs/cars/data/parts/**/*.yaml files.

Checks structure, required fields, and that claim_keys are unique across all parts.
Used as a CI gate before sync.

Usage:
    python -m packs.cars.pipeline.parts.validate_part_yaml
    python -m packs.cars.pipeline.parts.validate_part_yaml packs/cars/data/parts/engine/k9k.yaml
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml
from packs.cars.pipeline.paths import REPO_ROOT

from packs.cars.pipeline.util.domains import VALID_DOMAINS
from packs.cars.pipeline.stoplists import mentions_foreign_manufacturer_code, mentions_sibling_code
from packs.cars.pipeline.catalog.registry import (
    DETECTIONS, component_ids, detection_of, subsystem_of,
)

PARTS_DIR = REPO_ROOT / "packs" / "cars" / "data" / "parts"

REQUIRED_PART_FIELDS = {"part_id", "part_type", "display_name", "manufacturer", "claims"}
VALID_PART_TYPES = {"engine", "transmission", "turbo", "fuel_intake", "exhaust", "cooling", "electrical", "body"}
REQUIRED_CLAIM_FIELDS = {"claim_key", "title", "kind", "domain", "severity", "status", "rationale", "inspection_advice"}
VALID_KINDS = {"known_issue", "maintenance", "recall"}
VALID_SEVERITIES = {"high", "medium", "low"}
VALID_STATUSES = {"draft", "verified", "review", "held", "rejected"}

# ── schema v3 (overhaul Phase 2) ────────────────────────────────────────
# All optional at the claim level (omitted = v2 behaviour) but validated
# strictly when present, so the shape can never drift silently.
_BILINGUAL_PAIRS = {  # EN field -> required TR twin (cleanup-script invariant,
    "title": "title_tr",           # now enforced at write time)
    "rationale": "rationale_tr",
    "inspection_advice": "inspection_advice_tr",
}
_BUILD_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")
_COMPONENT_IDS = component_ids()  # snapshot at import: registry is static data


def _domain_family_agrees(domain: str, subsystem: str) -> bool:
    """True when a claim's domain plausibly belongs to the component's subsystem.

    'engine' claims on engine/* components obviously agree; 'brakes' on
    engine/cooling does not. Conservative: unknown mappings return True so
    the check never blocks a legitimate new combination.

    Legitimate crossings encoded below (each from real claims):
    - 'electrical' attaches to sensors/modules in ANY family (a crank sensor
      is an engine component carrying an electrical-domain claim);
    - 'engine' covers emissions/* hardware bolted to the engine (EGR, DPF);
    - 'emissions' covers engine-mounted sensors (lambda/O2);
    - 'fuel system' covers emissions/* injection-adjacent hardware.
    """
    family = subsystem.split("/", 1)[0]
    _AGREES = {
        "engine": {"engine", "emissions"},
        "transmission": {"transmission"},
        "emissions": {"emissions", "engine"},
        "brakes": {"brakes"},
        "suspension": {"suspension"},
        "electrical": None,             # electrical claims live in every family
        "body": {"body"},
        "cooling": {"engine"},          # engine/cooling components
        "fuel system": {"engine", "emissions"},
        "general": None,                # agrees with everything
    }
    ok = _AGREES.get(domain)
    if ok is None or not ok:            # unmapped, 'electrical', 'general': never block
        return True
    return family in ok


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

    # code_family is how catalog_sibling_families() (packs/cars/pipeline/stoplists.py)
    # derives sibling-code groups without a hand-maintained registry — only
    # meaningful for engine/transmission parts, which are the ones that carry
    # an alphanumeric engineering code at risk of cross-part confusion
    # (docs/design_flaws.md Flaw 1). generate_part_scaffold() defaults new
    # parts to a singleton family, so this should never actually fire for a
    # part created after that fix — a hard check catches anything hand-edited
    # around it.
    if part_type in ("engine", "transmission") and not data.get("code_family"):
        errors.append(f"{path}: missing required field 'code_family' (engine/transmission parts must declare one)")

    claims = data.get("claims", [])
    if not isinstance(claims, list):
        errors.append(f"{path}: 'claims' must be a list")
        return errors

    own_makes: set[str] = set(str(data.get("manufacturer") or "").lower().split("_"))
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

        domain = claim.get("domain", "")
        if domain not in VALID_DOMAINS:
            errors.append(
                f"{loc}: invalid domain {domain!r}, must be one of {sorted(VALID_DOMAINS)} "
                f"(run packs.cars.pipeline.normalize_domains to fix)"
            )

        status = claim.get("status", "")
        if status not in VALID_STATUSES:
            errors.append(f"{loc}: invalid status {status!r}")

        if kind == "maintenance" and not claim.get("maintenance"):
            errors.append(f"{loc}: maintenance claim missing 'maintenance' block")

        # Optional model-year window (applies_when.applies_year_from/to): when
        # present, bounds must be integers and from <= to. This is the sync gate,
        # so a malformed window fails here instead of silently mis-scoping a claim.
        # (bool is an int subclass in Python — reject it explicitly.)
        aw = claim.get("applies_when")
        if isinstance(aw, dict):
            yf = aw.get("applies_year_from")
            yt = aw.get("applies_year_to")
            for name, val in (("applies_year_from", yf), ("applies_year_to", yt)):
                if val is not None and (isinstance(val, bool) or not isinstance(val, int)):
                    errors.append(f"{loc}: applies_when.{name} must be an integer, got {val!r}")
            if isinstance(yf, int) and not isinstance(yf, bool) \
               and isinstance(yt, int) and not isinstance(yt, bool) and yf > yt:
                errors.append(
                    f"{loc}: applies_when.applies_year_from ({yf}) > applies_year_to ({yt})"
                )

        if status in ("verified", "review") and kind != "maintenance":
            sources = claim.get("sources", [])
            if not sources:
                errors.append(f"{loc}: servable non-maintenance claim has no sources")

        # ── schema v3 (overhaul Phase 2) ─────────────────────────────
        # Bilingual invariant (folded from translate_claims.py's cleanup pass):
        # an EN field present without its TR twin ships mixed-language text to
        # buyers. Hard check so the half-finished translation pass becomes a
        # pipeline invariant instead of a recurring mop.
        for en, tr in _BILINGUAL_PAIRS.items():
            if claim.get(en) and not claim.get(tr):
                errors.append(f"{loc}: {en!r} present without {tr!r} (bilingual invariant)")

        component_id = claim.get("component_id")
        if component_id is not None:
            if component_id not in _COMPONENT_IDS:
                errors.append(
                    f"{loc}: unknown component_id {component_id!r} — must resolve in "
                    f"packs/cars/pipeline/catalog/components.yaml"
                )
            else:
                # The claim's domain should agree with the component's
                # subsystem family — 'brakes' claims on an engine component
                # are almost always misattributed.
                sub = subsystem_of(component_id) or ""
                if domain in VALID_DOMAINS and sub and not _domain_family_agrees(domain, sub):
                    errors.append(
                        f"{loc}: domain {domain!r} disagrees with component "
                        f"{component_id!r} subsystem {sub!r}"
                    )

        detection = claim.get("detection")
        if detection is not None:
            if detection not in DETECTIONS:
                errors.append(f"{loc}: detection {detection!r} must be one of {sorted(DETECTIONS)}")
            elif component_id in _COMPONENT_IDS:
                comp_det = detection_of(component_id)
                if detection != comp_det:
                    errors.append(
                        f"{loc}: detection {detection!r} contradicts component "
                        f"{component_id!r} registry detection {comp_det!r}"
                    )

        symptoms = claim.get("symptoms")
        if symptoms is not None:
            if not isinstance(symptoms, list) or not all(isinstance(s, str) for s in symptoms):
                errors.append(f"{loc}: symptoms must be a list of strings")

        window = claim.get("affected_build_window")
        if window is not None:
            if not isinstance(window, dict) or set(window) - {"from", "to"}:
                errors.append(f"{loc}: affected_build_window must be a mapping with from/to only")
            else:
                for k in ("from", "to"):
                    if k in window and not _BUILD_MONTH.fullmatch(str(window[k] or "")):
                        errors.append(f"{loc}: affected_build_window.{k} must be YYYY-MM, got {window[k]!r}")

        cost = claim.get("repair_cost_band")
        if cost is not None:
            if not isinstance(cost, dict) or set(cost) - {"currency", "min", "max"}:
                errors.append(f"{loc}: repair_cost_band must have currency/min/max only")
            else:
                for bound in ("min", "max"):
                    val = cost.get(bound)
                    if not isinstance(val, int) or isinstance(val, bool) or val < 0:
                        errors.append(f"{loc}: repair_cost_band.{bound} must be a non-negative integer")
                if "currency" in cost and not re.fullmatch(r"[A-Z]{3}", str(cost["currency"] or "")):
                    errors.append(f"{loc}: repair_cost_band.currency must be ISO 4217 (e.g. TRY)")

        fix = claim.get("fix_available")
        if fix is not None and not isinstance(fix, str):
            errors.append(f"{loc}: fix_available must be a string")

        # Sibling-code contamination (docs/design_flaws.md Flaw 1): a claim
        # naming a sibling component's code (same family, different physical
        # part — e.g. DQ200 in a dq381.yaml claim) without also naming this
        # part's own code is almost certainly mislabeled, not evidence about
        # this part. Hard check so bad output fails at write time instead of
        # relying on a one-off cleanup pass.
        claim_text = " ".join(
            str(claim.get(f, "") or "") for f in ("title", "rationale")
        )
        if mentions_sibling_code(claim_text, part_id):
            errors.append(
                f"{loc}: claim text names a sibling component's code but not "
                f"{part_id}'s own — likely filed under the wrong part (run "
                f"packs.cars.pipeline.fix_sibling_contamination): {claim.get('title', '')!r}"
            )

        # Cross-manufacturer contamination: a claim naming another
        # manufacturer's engine/transmission code with no shared brand word
        # at all (e.g. a Renault part's claim citing VW's "EA211") — see
        # mentions_foreign_manufacturer_code's docstring.
        if mentions_foreign_manufacturer_code(claim_text, own_makes):
            errors.append(
                f"{loc}: claim text names another manufacturer's engine/transmission "
                f"code — likely filed under the wrong part: {claim.get('title', '')!r}"
            )

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
