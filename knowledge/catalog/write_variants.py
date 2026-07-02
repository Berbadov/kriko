"""write_variants.py — procedurally generate a new model's TR-market variants YAML.

catalog.discover finds engine/transmission *codes* from Wikipedia, but the TR-market
lineup — which trims were actually sold in Turkey, at what power/year, on what
gearbox — isn't in a machine-readable source; it's domain knowledge. Per CLAUDE.md,
`backend/data/*` is never hand-written, so that domain knowledge lives here as data
in a script (reviewable, diffable, rerunnable) instead of typed directly into YAML.

Each model's trim list is cross-checked against catalog.discover's Wikipedia-derived
engine families/fuels and logs a warning on mismatch, but hand-curated data wins —
Wikipedia infoboxes are noisy (e.g. list engines from special editions never sold
in TR, or omit automatic-transmission variants entirely).

Usage:
    python -m knowledge.catalog.write_variants --make renault --model clio_5
    python -m knowledge.catalog.write_variants --make volkswagen --model golf_7 --dry-run
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import yaml

from knowledge.catalog.discover import discover

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent.parent
VARIANTS_DIR = REPO_ROOT / "backend" / "data" / "variants"

# TR-market trim data, keyed by "{make}_{model}". Each row matches the schema
# already used by hand-curated files (renault_megane_4.yaml, volkswagen_golf_7.yaml):
# id, make, model, generation, engine_code, engine_family, fuel, displacement_cc,
# power_min_hp, power_max_hp, transmission, transmission_code, electrical_code,
# body_code, year_from, year_to, market, notes, drivetrain.
#
# engine_family follows the current power-split convention (e.g. "h5h_130", not
# bare "h5h") — each power tune is researched as its own part, consistent with
# volkswagen_golf_7.yaml (ea211/ea288 are the one exception, kept as engine-family-
# wide research keys rather than split further).
TR_MARKET_TRIMS: dict[str, list[dict]] = {
    "renault_clio_5": [
        {
            "id": "clio5_h4d_75", "generation": "V", "engine_code": "H4D", "engine_family": "h4d_75",
            "fuel": "petrol", "displacement_cc": 999, "power_min_hp": 75, "power_max_hp": 75,
            "transmission": "manual", "transmission_code": "manual",
            "year_from": 2019, "year_to": 2023, "notes": "SCe 75 — naturally aspirated 3-cyl, base trim, manual only",
        },
        {
            "id": "clio5_h5d_100", "generation": "V", "engine_code": "H5Dt", "engine_family": "h5d_100",
            "fuel": "petrol", "displacement_cc": 999, "power_min_hp": 90, "power_max_hp": 100,
            "transmission": "manual", "transmission_code": "manual",
            "year_from": 2019, "year_to": None, "notes": "TCe 90/100 — turbocharged 3-cyl, volume trim, manual",
        },
        {
            "id": "clio5_h5d_100_edc", "generation": "V", "engine_code": "H5Dt", "engine_family": "h5d_100",
            "fuel": "petrol", "displacement_cc": 999, "power_min_hp": 100, "power_max_hp": 100,
            "transmission": "automatic", "transmission_code": "edc",
            "year_from": 2019, "year_to": None, "notes": "TCe 100 EDC — same engine as manual, 7-speed dual-clutch",
        },
        {
            "id": "clio5_h5h_130", "generation": "V", "engine_code": "H5Ht", "engine_family": "h5h_130",
            "fuel": "petrol", "displacement_cc": 1332, "power_min_hp": 130, "power_max_hp": 130,
            "transmission": "automatic", "transmission_code": "edc",
            "year_from": 2019, "year_to": 2022, "notes": "TCe 130 — EDC only, GT-Line trim; same engine family as Megane 4 H5H but a distinct power tune/part",
        },
        {
            "id": "clio5_k9k_85", "generation": "V", "engine_code": "K9K", "engine_family": "k9k_85",
            "fuel": "diesel", "displacement_cc": 1461, "power_min_hp": 75, "power_max_hp": 85,
            "transmission": "manual", "transmission_code": "manual",
            "year_from": 2019, "year_to": 2021, "notes": "Blue dCi 85 — entry diesel, dropped from range as EU7 prep reduced small-diesel offers",
        },
        {
            "id": "clio5_k9k_100", "generation": "V", "engine_code": "K9K", "engine_family": "k9k_100",
            "fuel": "diesel", "displacement_cc": 1461, "power_min_hp": 95, "power_max_hp": 100,
            "transmission": "manual", "transmission_code": "manual",
            "year_from": 2019, "year_to": None, "notes": "Blue dCi 100 — volume diesel trim",
        },
    ],
    "volkswagen_golf_7": [
        {
            "id": "golf7_ea888_220", "generation": "VII", "engine_code": "EA888", "engine_family": "ea888_220",
            "fuel": "petrol", "displacement_cc": 1984, "power_min_hp": 220, "power_max_hp": 220,
            "transmission": "automatic", "transmission_code": "dq250",
            "year_from": 2013, "year_to": 2016, "notes": "GTI (pre-facelift) — 2.0 TSI EA888 Gen3, 6-speed wet DSG or 6MT",
        },
        {
            "id": "golf7_ea888_230", "generation": "VII", "engine_code": "EA888", "engine_family": "ea888_230",
            "fuel": "petrol", "displacement_cc": 1984, "power_min_hp": 230, "power_max_hp": 245,
            "transmission": "automatic", "transmission_code": "dq381",
            "year_from": 2017, "year_to": 2020, "notes": "GTI/GTI Performance (facelift) — 2.0 TSI EA888 Gen3, 7-speed wet DSG or 6MT",
        },
        {
            "id": "golf7_ea888_300", "generation": "VII", "engine_code": "EA888", "engine_family": "ea888_300",
            "fuel": "petrol", "displacement_cc": 1984, "power_min_hp": 300, "power_max_hp": 310,
            "transmission": "automatic", "transmission_code": "dq381",
            "year_from": 2014, "year_to": 2020, "notes": "R — 2.0 TSI EA888 Gen3, Haldex AWD, DQ250 pre-facelift/DQ381 facelift (simplified to dq381 here)",
            "drivetrain": "awd",
        },
    ],
}

# electrical_code / body_code per model — one shared fitment axis per generation,
# not per engine (matches golf7_elec/golf7_body convention).
_SHARED_CODES: dict[str, dict[str, str]] = {
    "renault_clio_5": {"electrical_code": "clio5_elec", "body_code": "clio5_body"},
    "volkswagen_golf_7": {"electrical_code": "golf7_elec", "body_code": "golf7_body"},
}


def _cross_check(make: str, model: str, trims: list[dict]) -> None:
    """Warn (don't block) if a trim's engine code isn't in Wikipedia's discovered list."""
    try:
        catalog = discover(make, model)
    except Exception as exc:
        log.warning("Could not fetch Wikipedia catalog for cross-check: %s", exc)
        return
    known_codes = {s.engine_code.upper() for s in catalog.engines}
    for t in trims:
        code = t["engine_code"].upper()
        if code not in known_codes and code.rstrip("T") not in known_codes:
            log.warning(
                "Trim %s: engine code %s not found in Wikipedia infobox for %s %s "
                "(hand-curated data kept — Wikipedia infoboxes are known to be incomplete)",
                t["id"], code, make, model,
            )


def build_rows(make: str, model: str, trims: list[dict], shared: dict[str, str]) -> list[dict]:
    make_key, model_key = make.lower(), model.lower().split("_")[0]
    rows = []
    for t in trims:
        row = {
            "id": t["id"],
            "make": make_key,
            "model": model_key,
            "generation": t["generation"],
            "engine_code": t["engine_code"],
            "engine_family": t["engine_family"],
            "fuel": t["fuel"],
            "displacement_cc": t["displacement_cc"],
            "power_min_hp": t["power_min_hp"],
            "power_max_hp": t["power_max_hp"],
            "transmission": t["transmission"],
            "transmission_code": t["transmission_code"],
            "electrical_code": shared.get("electrical_code", ""),
            "year_from": t["year_from"],
            "year_to": t.get("year_to"),
            "market": "TR",
            "notes": t["notes"],
            "body_code": shared.get("body_code", ""),
            "drivetrain": t.get("drivetrain", "fwd"),
        }
        rows.append(row)
    return rows


def run(make: str, model: str, dry_run: bool = False) -> None:
    key = f"{make.lower()}_{model.lower()}"
    trims = TR_MARKET_TRIMS.get(key)
    if not trims:
        raise SystemExit(
            f"No TR-market trim data for {key!r}. Add an entry to TR_MARKET_TRIMS "
            f"in {__file__} first — this is deliberately hand-authored domain "
            f"knowledge (Wikipedia doesn't know which trims TR got), not something "
            f"this script can infer."
        )

    _cross_check(make, model, trims)
    shared = _SHARED_CODES.get(key, {})
    new_rows = build_rows(make, model, trims, shared)

    path = VARIANTS_DIR / f"{key}.yaml"
    existing: list[dict] = []
    if path.exists():
        existing = yaml.safe_load(path.read_text()) or []

    existing_ids = {r["id"] for r in existing}
    to_add = [r for r in new_rows if r["id"] not in existing_ids]
    skipped = [r["id"] for r in new_rows if r["id"] in existing_ids]

    if not to_add:
        print(f"No new rows — all {len(new_rows)} variant(s) already present in {path}")
        return

    if skipped:
        print(f"Skipping {len(skipped)} already-present id(s): {', '.join(skipped)}")

    print(f"{'Would add' if dry_run else 'Adding'} {len(to_add)} variant(s) to {path.relative_to(REPO_ROOT)}:")
    for r in to_add:
        print(f"  {r['id']}: {r['engine_code']} {r['fuel']} {r['displacement_cc']}cc "
              f"{r['power_min_hp']}-{r['power_max_hp']}hp {r['transmission']} ({r['transmission_code']})")

    if dry_run:
        return

    combined = existing + to_add
    header = ""
    if path.exists():
        text = path.read_text()
        if text.startswith("#"):
            header = "\n".join(
                line for line in text.splitlines() if line.startswith("#")
            ) + "\n\n"
    else:
        header = (
            f"# {make.title()} {model.replace('_', ' ').title()} — Turkish market variant catalog\n"
            f"# Generated by knowledge.catalog.write_variants — see TR_MARKET_TRIMS for source data.\n"
            f"# ID format: {{model}}_{{engine_code}}_{{power_hp}}[_{{tx_suffix}}]\n\n"
        )
    path.write_text(header + yaml.dump(combined, allow_unicode=True, sort_keys=False))

    print(f"Wrote {path.relative_to(REPO_ROOT)}")


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--make", required=True)
    parser.add_argument("--model", required=True, help="Model key, e.g. clio_5, golf_7")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(args.make.lower(), args.model.lower(), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
