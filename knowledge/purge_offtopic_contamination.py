"""purge_offtopic_contamination.py — one-off cleanup of two contamination
classes knowledge.fix_sibling_contamination.py (Flaw 1) structurally cannot
catch, found by manual audit of every engine/transmission part YAML while
scoping the Flaw 2 K9K/H5F/H5H power-tune merge:

1. Non-automotive content: h5d_100.yaml and h5h_130.yaml both carry claims
   that are verbatim about a Vaillant/Falke gas combi boiler (HVAC "F5"/"E5"
   fault codes, hot-water NTC sensor, chimney/hermetic exhaust routing) — not
   a car part at all. mentions_sibling_code() only recognizes registered
   engine/transmission codes, so content with no code collision at all is
   invisible to it regardless of registry completeness.

2. Cross-manufacturer bleed: h4d_75.yaml (Renault) explicitly names a VW "1.0
   TSI (EA211)" engine in its own rationale text, and h5d_100.yaml (Renault)
   carries a claim about "the 7-speed dry clutch DSG transmission paired with
   the 1.0 TSI engine" (VW's DQ200 pairing, not Renault's). These aren't
   same-manufacturer sibling-code confusion (what SIBLING_CODE_FAMILIES
   models) — forcing VW and Renault codes into one "family" would be
   semantically wrong and would misfire on legitimate engine-file mentions of
   a paired gearbox code. Caught here by explicit claim_key instead.

DELETES (not tombstones) the claim_key, mirroring fix_sibling_contamination.py:
these aren't genuine claims about the part they're filed under that need to
stay suppressed from re-adding — they're claims about a *different* engine or
a different appliance entirely, so there's nothing to preserve for audit
under this part_id.

Usage:
    python -m knowledge.purge_offtopic_contamination              # dry run
    python -m knowledge.purge_offtopic_contamination --apply       # write changes
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent
PARTS_DIR = REPO_ROOT / "backend" / "data" / "parts"

# path (relative to PARTS_DIR) -> set of claim_keys confirmed off-topic by manual review
OFFTOPIC_CLAIM_KEYS: dict[str, set[str]] = {
    "engine/h4d_75.yaml": {
        "h4d_75_engine_turbocharger_prematu",       # explicitly "1.0 TSI (EA211)"
        "h4d_75_engine_timing_belt_degradat",       # explicitly "EA211 evo"
        "h4d_75_emissions_gpf_(gasoline_partic",    # explicitly "1.0 TSI EA211"
    },
    "engine/h5d_100.yaml": {
        "h5d_100_general_fan_motor_rulman_aşı",       # Vaillant boiler fan motor
        "h5d_100_electrical_elektrik_dalgalanmal",    # boiler fan motor / F5 fault code
        "h5d_100_electrical_fan_motoru_bobin_yan",    # boiler fan motor coil / F5 fault code
        "h5d_100_general_nem_ve_su_sızıntısı_",       # boiler fan motor moisture ingress
        "h5d_100_electrical_elektronik_kart_ve_f",    # boiler ECU/fan motor / F5 fault code
        "h5d_100_electrical_ntc_(sıcaklık_sensör",    # explicitly "Vaillant boilers" NTC sensor
        "h5d_100_transmission_dsg_dq200_7-speed_dr",  # explicitly "paired with the 1.0 TSI engine" (VW)
    },
    "engine/h5h_130.yaml": {
        "h5h_130_fuel system_gas_blockage_in_falk",   # Falke combi boiler
        "h5h_130_emissions_exhaust_gas_system_f",     # Falke HT/BT combi exhaust routing
        "h5h_130_electrical_faulty_hot_water_tem",    # combi hot-water NTC sensor
        "h5h_130_general_chronic_limescale_(k",       # combi heat-exchanger limescale
    },
}


def _purge_file(path: Path, keys: set[str], apply: bool) -> list[str]:
    data = yaml.safe_load(path.read_text()) or {}
    claims = data.get("claims", [])
    if not isinstance(claims, list):
        return []

    kept: list[dict] = []
    removed: list[str] = []
    for claim in claims:
        if isinstance(claim, dict) and claim.get("claim_key") in keys:
            removed.append(f"{claim['claim_key']}: {claim.get('title')}")
        else:
            kept.append(claim)

    if removed and apply:
        data["claims"] = kept
        path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False))

    return removed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
    args = parser.parse_args()

    print(f"{'APPLYING' if args.apply else 'DRY RUN'}\n")

    total = 0
    for rel_path, keys in OFFTOPIC_CLAIM_KEYS.items():
        path = PARTS_DIR / rel_path
        removed = _purge_file(path, keys, args.apply)
        if removed:
            print(f"  {path.relative_to(REPO_ROOT)}:")
            for r in removed:
                print(f"    - {r}")
            total += len(removed)

    print(f"\nTOTAL: {total} off-topic claim(s) removed")
    if not args.apply:
        print("\nDry run — no files written. Re-run with --apply to write changes.")


if __name__ == "__main__":
    main()
