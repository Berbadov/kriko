"""migrate_v3.py — backfill component_id/detection on existing part claims.

One-shot migration for overhaul Phase 0/2: walks backend/data/parts/**/*.yaml
and, for every claim without a component_id, matches the claim's text against
the component registry's *attribution_safe* aliases only (never search_only —
a shared alias cannot attribute, that's the whole point of the two tiers).

Rules, in order:
  1. Alias found in the claim TITLE (highest signal — titles lead with the
     failing component) wins over one found only in the rationale.
  2. Still ambiguous (several components matched at the same level) → skip
     and report. Never guess: an unmatched claim is a visible gap; a wrong
     component_id silently misattributes.
  3. No match → component_id stays absent, counted in the report. The serving
     layer treats missing component_id as detection-neutral.

Usage:
    python -m knowledge.parts.migrate_v3            # dry run, report only
    python -m knowledge.parts.migrate_v3 --write    # apply, then re-validate
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

from knowledge.catalog.registry import all_attribution_safe_aliases, detection_of

PARTS_DIR = Path(__file__).parent.parent.parent / "backend" / "data" / "parts"

# Hand-curated fallback: failure-mode phrasing -> component_id. Applied only
# when the attribution-safe alias pass fails. Ordered — first regex hit wins,
# so where a title names two components the entry higher in this list is the
# primary one (e.g. "thermostat and water pump" -> water pump: on the R9M the
# pump is the part that fails and drags the belt). Every entry names a phrase
# that can only mean this component; generic prose ("reliability issues",
# "jerky shifts") matches nothing and stays component-free on purpose.
#
# A phrase-map hit is additionally checked against the claim's part-file
# family (engine/transmission/electrical/body) — a component from an alien
# family means the claim itself is misfiled (the known contamination flaw),
# so it stays component-free rather than blessing the misfiling.
_PHRASE_MAP: list[tuple[str, str]] = [
    # --- specific pumps first: "fuel pressure loss"/"pressure sensor" prose
    # must not shadow them, and HP pump is how sources spell high-pressure ---
    (r"water pump", "engine_water_pump"),
    (r"hp pump|high[- ]pressure pump", "engine_high_pressure_pump"),
    (r"fuel pump|fuel system", "engine_fuel_pump"),
    (r"oil pressure|oil pump", "engine_oil_pump"),
    # --- emissions before ignition: "AdBlue injector" is the SCR doser ---
    (r"adblue|\bscr\b", "emissions_scr_adblue"),
    (r"nox sensor", "emissions_nox_sensor"),
    (r"dpf|particulate filter|\bfap\b", "emissions_dpf"),
    (r"egr", "emissions_egr"),
    # --- transmission (DCT ordering: specific before generic) ---
    (r"dual[- ]?mass flywheel|\bdmf\b|flywheel", "transmission_dual_mass_flywheel"),
    (r"mechatronic|mekatronik|accumulator|hydraulic pump",
     "transmission_dct_mechatronics"),
    (r"torque converter", "transmission_torque_converter"),
    (r"valve body", "transmission_at_valve_body"),
    (r"master cylinder|slave cylinder|clutch (pedal|master|slave|hydraulics)",
     "transmission_clutch_master_slave"),
    (r"clutch disc|manual.*clutch|clutch.*manual", "transmission_clutch_disc"),
    (r"clutch|\bk1\b|shudder|judder", "transmission_dct_clutch_pack"),
    (r"fork|synchroni[sz]er|syncro|hub spline", "transmission_dct_fork_synchronizer"),
    (r"bearing", "transmission_dct_differential_bearings"),
    (r"speed sensor|pressure sensor", "transmission_dct_pressure_sensor"),
    (r"solenoid", "transmission_dct_mechatronics"),
    # --- timing / valvetrain (order: chain/belt before tensioner/phaser) ---
    (r"timing chain|chain stretch|triger zinciri", "engine_timing_chain"),
    (r"timing belt|cam belt|triger kayışı", "engine_timing_belt"),
    (r"tensioner", "engine_timing_tensioner"),
    (r"camshaft|phaser|variable valve|\bvvt\b", "engine_timing_variable_valve"),
    # --- engine internals / lubrication ---
    (r"piston ring|oil consumption|ya[ğg] t[üu]ketimi|oil starvation|pcv",
     "engine_oil_consumption"),
    (r"head gasket", "engine_head_gasket"),
    (r"low compression|balancer shaft|bottom end", "engine_bottom_end"),
    # --- cooling ---
    (r"thermostat", "engine_thermostat"),
    (r"radiator|coolant leak", "engine_radiator"),
    (r"intercooler", "engine_intercooler"),
    # --- air path ---
    (r"turbo actuator|actuator", "engine_turbo_actuator"),
    (r"turbo|turbocharger", "engine_turbocharger"),
    (r"boost sensor|map sensor", "engine_boost_sensor"),
    (r"intake carbon|carbon build|gdi carbon|intake valve", "engine_intake_carbon"),
    (r"swirl flap", "emissions_swirl_flaps"),
    (r"throttle body", "engine_throttle_body"),
    # --- fuel / ignition ---
    (r"injector", "engine_injectors"),
    (r"spark plug|ignition coil|coil pack|coil failure|misfire", "engine_spark_ignition"),
    # --- emissions (rest) ---
    (r"catalytic converter", "emissions_catalytic_converter"),
    (r"o2 sensor|lambda sensor", "engine_o2_sensor"),
    # --- electrical / body ---
    (r"infotainment|openr|carplay|e[- ]call|\bsos\b|connectivity|ota|black screen|"
     r"software crash|software instab", "electrical_infotainment"),
    (r"instrument cluster|warning light", "electrical_instrument_cluster"),
    (r"power steering|steering assist|\beps\b", "steering_electric_power_steering"),
    (r"charging door|recharge|range estimation", "ev_charging"),
    (r"battery|\b48v\b|charging", "electrical_battery_charging"),
    (r"ground connection|wiring|loom|harness", "electrical_wiring_loom"),
    (r"blower resistor", "body_hvac_blower"),
    (r"climate control|air conditioning|klima|compressor", "body_ac_compressor"),
    (r"parking sensor", "electrical_parking_sensors"),
    (r"keyless", "electrical_keyless"),
    (r"starter", "electrical_starter_motor"),
    # --- body / suspension / brakes ---
    (r"rust|corrosion|korozyon", "body_rust_corrosion"),
    (r"water (ingress|leak)|seal.*leak|leak.*cabin|boot.*leak|speaker seal",
     "body_water_ingress"),
    (r"sunroof", "body_sunroof_drain"),
    (r"window regulator", "body_window_regulator"),
    (r"shock absorber|amortis[öo]r|suspension wear", "suspension_shock_absorbers"),
    (r"stabili[sz]er|anti[- ]roll|sway bar", "suspension_stabilizer_links"),
    (r"control arm|bushing", "suspension_control_arm_bushings"),
    (r"wheel bearing", "suspension_wheel_bearings"),
    (r"coil spring", "suspension_coil_springs"),
    (r"strut mount", "suspension_strut_mounts"),
    (r"caliper|handbrake|el freni", "brakes_caliper_handbrake_mech"),
    (r"electronic parking brake|\bepb\b", "brakes_electronic_parking_brake"),
    (r"\babs\b", "brakes_abs_module"),
    (r"brake fluid|servo", "brakes_vacuum_servo"),
    # --- generic fallbacks, last by construction ---
    # Any pump still unmatched in a gearbox-file context is the gearbox oil
    # pump (start-stop pump, "pump inherits DQ200 risk"); engine pumps are
    # all matched by their specific entries above.
    (r"start[- ]stop pump|pump (failure|inherits|risk)|\bpump\b.*(dsg|dq\d|dw\d|edc)|"
     r"(dsg|dq\d|dw\d|edc).*\bpump\b", "transmission_dct_gearbox_oil_pump"),
]
_PHRASE_MAP = [(re.compile(rf"(?i){pat}"), cid) for pat, cid in _PHRASE_MAP]

# Component families each part-file family may legitimately carry. Claims
# matching a component outside the part file's family are contamination
# (design_flaws.md Flaw 1) and stay component-free.
_FAMILY_OK: dict[str, frozenset[str]] = {
    "engine": frozenset({"engine", "emissions", "electrical", "ev"}),
    "transmission": frozenset({"transmission"}),
    "electrical": frozenset({"electrical", "ev", "engine", "emissions", "steering",
                             "body"}),  # body-HVAC electrics (blower, AC compressor)
    "body": frozenset({"body", "suspension", "steering", "brakes"}),
}


def _family_of(component_id: str) -> str:
    return component_id.split("_", 1)[0]


def _phrase_match(text: str, part_family: str | None = None) -> str | None:
    """First curated phrase hit whose component fits the part file's family.

    ``part_family`` is the part file's directory name (engine/transmission/
    electrical/body); None disables the guard (accept any hit).
    """
    allowed = _FAMILY_OK.get(part_family or "")
    for pat, cid in _PHRASE_MAP:
        if pat.search(text):
            if allowed is None or _family_of(cid) in allowed:
                return cid
            continue  # alien family: skip this hit, keep scanning
    return None


def _match_components(text: str, aliases: dict[str, list[str]]) -> set[str]:
    """Components whose attribution_safe alias occurs in text (word-boundary)."""
    if not text:
        return set()
    found: set[str] = set()
    for alias, cids in aliases.items():
        if re.search(rf"(?i)(?<![a-z]){re.escape(alias)}(?![a-z])", text):
            found.update(cids)
    return found


def migrate(dry_run: bool = True) -> int:
    aliases = all_attribution_safe_aliases()
    stats = {"resolved": 0, "ambiguous": 0, "unmatched": 0, "already": 0}
    per_part: dict[str, tuple[int, int, int]] = {}

    for path in sorted(PARTS_DIR.rglob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        if not isinstance(data, dict):
            continue
        part_family = path.parent.name  # engine/transmission/electrical/body
        claims = data.get("claims") or []
        part_stats = [0, 0, 0]  # resolved, ambiguous, unmatched

        for claim in claims:
            if not isinstance(claim, dict):
                continue
            if claim.get("component_id"):
                stats["already"] += 1
                # Backfill detection for already-attributed claims (registry
                # default per component; an explicit claim-level value wins).
                if not claim.get("detection"):
                    det = detection_of(claim["component_id"])
                    if det:
                        claim["detection"] = det
                        part_stats[0] += 1
                        stats["resolved"] += 1
                continue

            title = str(claim.get("title", "") or "")
            rationale = str(claim.get("rationale", "") or "")
            title_tr = str(claim.get("title_tr", "") or "")

            in_title = _match_components(title, aliases) or _match_components(title_tr, aliases)
            in_text = _match_components(f"{title} {rationale}", aliases)

            # Resolution order, most-confident first: a unique attribution-safe
            # alias in the title, then the curated phrase map on the title,
            # then aliases across title+rationale, then the phrase map there.
            # Ambiguity at every level stays ambiguous — reported, not guessed.
            chosen = None
            if len(in_title) == 1:
                chosen = next(iter(in_title))
            elif (hit := _phrase_match(f"{title} {title_tr}", part_family)):
                chosen = hit
            elif not in_title and len(in_text) == 1:
                chosen = next(iter(in_text))
            elif (hit := _phrase_match(rationale, part_family)):
                chosen = hit

            if chosen:
                claim["component_id"] = chosen
                det = detection_of(chosen)
                if det:
                    claim["detection"] = det
                stats["resolved"] += 1
                part_stats[0] += 1
            elif in_title or in_text:
                stats["ambiguous"] += 1
                part_stats[1] += 1
                print(f"  AMBIGUOUS [{path.stem}] {title!r}: candidates "
                      f"{sorted(in_title or in_text)}")
            else:
                stats["unmatched"] += 1
                part_stats[2] += 1

        per_part[path.stem] = tuple(part_stats)
        if not dry_run and part_stats[0]:
            path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False))

    print(f"\n{'DRY RUN' if dry_run else 'APPLIED'} — per part (resolved/ambiguous/unmatched):")
    for part, (r, a, u) in sorted(per_part.items()):
        if r or a or u:
            print(f"  {part:<12} {r}/{a}/{u}")
    print(f"\nTotals: {stats}")
    if stats["ambiguous"] or stats["unmatched"]:
        print("Unresolved claims stay component-free — visible gaps, not guesses.")
    return 0


if __name__ == "__main__":
    sys.exit(migrate(dry_run="--write" not in sys.argv))
