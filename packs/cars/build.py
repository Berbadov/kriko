"""Export the legacy car catalog into a pack file.

    python -m packs.cars.build --out dist/cars.kpack

This is a migration, not the general pack builder. `kriko/pack/build.py` reads a
standard YAML layout; nothing about a decade of accreted car YAML is standard,
so this script reads the legacy shapes directly and writes the same rows.

What it converts:

    packs/cars/data/variants/*.yaml   -> subjects(kind=product) + attributes
    packs/cars/data/parts/**/*.yaml   -> subjects(kind=part) + claims + evidence
    packs/cars/data/fitment/*.yaml    -> relations(part_of)
    knowledge/catalog/components.yaml -> claim component/subsystem/detection
    knowledge/catalog/source_tiers.yaml -> source_tiers + tier_trust

Three conversions carry a decision rather than a mapping:

**`status` becomes rank.** See `[status_confidence]` in pack.toml.

**`year_from`/`year_to` become one row with a validity window**, not two
attributes. A production run of 2014-2020 is one fact about the car, and storing
it as bounds lets a listing year be tested against it without the engine knowing
what a model year is.

**Fitment edges keep their note string verbatim.** `resolver._GROUNDING_PART_RE`
parses "Part fitment: {id} ({type})" today, so preserving it keeps the parity
harness able to compare old and new attribution.

After Phase 6 the legacy directories move under `packs/cars/data/` and this
script is replaced by the standard builder.
"""

import argparse
import re
import tomllib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

from kriko.store import ids
from kriko.store.db import SCHEMA_VERSION, connect

REPO = Path(__file__).resolve().parent.parent.parent
PACK_ROOT = Path(__file__).resolve().parent

# The car data lives in the pack now. It arrived here from backend/data/ and
# knowledge/catalog/ unchanged — the golden parity record was re-verified
# across the move, so the relocation is provably lossless.
DATA = PACK_ROOT / "data"
CATALOG = PACK_ROOT / "vocabulary"
TRUST = PACK_ROOT / "trust"

# Codes that name a shape rather than a part. "manual" is not a gearbox anyone
# publishes failures about, and there is no part YAML for it.
PSEUDO_PART_CODES = {"manual"}

# Which fitment columns point at a part, and what kind of part each names.
FITMENT_KEYS = {
    "engine_family": "engine",
    "transmission_code": "transmission",
    "electrical_code": "electrical",
    "body_code": "body",
}


def _yaml(path: Path, default=None):
    if not path.exists():
        return default
    return yaml.safe_load(path.read_text(encoding="utf-8")) or default


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _num(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _vocabulary() -> list[dict]:
    """The car vocabulary, as rows. Everything normalize.py used to hard-code."""
    return _yaml(PACK_ROOT / "vocabulary" / "terms.yaml", [])


def _identity_of(variant: dict, keys: list[str]) -> dict:
    return {k: variant.get(k, "") for k in keys}


def _label(variant: dict) -> str:
    bits = [str(variant.get("make", "")).title(), str(variant.get("model", "")).title()]
    if variant.get("generation"):
        bits.append(str(variant["generation"]))
    if variant.get("engine_code"):
        bits.append(str(variant["engine_code"]))
    if variant.get("power_min_hp"):
        bits.append(f"{variant['power_min_hp']} hp")
    if variant.get("transmission_code") not in (None, "", "manual"):
        bits.append(str(variant["transmission_code"]).upper())
    return " ".join(b for b in bits if b)


# ── compatibility gates, as text signals ─────────────────────────────────
#
# These five checks lived in `backend/sync.py` and ran at ETL time, which froze
# their verdict into the claim-variant link and made it unrevisable. Here they
# run once at export and emit condition rows, so the same judgement is data the
# reader can inspect — and a better regex later is a rebuild, not a migration.
#
# All five share one shape: does the claim's OWN TEXT name hardware that rules
# out a car? A claim saying "DPF blockages (TDI models)" must not reach a petrol
# car merely because both share a body-electrics part file.
#
# Every gate emits `on_missing: ignore`. These are pure excluders: if the
# catalog does not know a car's drivetrain, that is not a reason to rank its
# claims lower, only a reason not to exclude. The mileage gates use `open`
# because there an unknown genuinely does reduce confidence; here it does not.

_DIESEL_RE = re.compile(r"\b(k9k|r9m|r9n|ea288|d[ck]i|tdi|diesel|dizel|adblue|dpf)\b", re.I)
_PETROL_RE = re.compile(
    r"\b(h5f|h5h|h4m|m5m|m5p|ea211|tce|tsi|puretech|petrol|benzin|gasoline)\b", re.I)
_EV_HYBRID_RE = re.compile(
    r"e-tech|\bhybrid\b|dc charging|ac charging|heat pump|state of charge|"
    r"precondition|traction battery|\bhv battery\b|"
    r"charging (?:port|door|impossible|abort)|trappe de recharge|"
    r"onboard charger|regenerative braking|\bev mode\b|\bkwh\b|fully electric", re.I)
_AWD_RE = re.compile(
    r"\bawd\b|\b4wd\b|\b4x4\b|4matic|quattro|4motion|xdrive|haldex|"
    r"all[- ]wheel drive|4\s*[çc]eker", re.I)
_RWD_RE = re.compile(r"\brwd\b|rear[- ]wheel drive|arkadan\s*iti[şs]", re.I)
_SCR_RE = re.compile(r"\b(adblue|ad\s?blue|scr|urea|def)\b", re.I)
_AUTO_ONLY_RE = re.compile(
    r"\b(dsg|dct|edc|cvt|tiptronic|s-tronic|powershift|mechatronic|mekatronik|"
    r"torque converter|dual[- ]clutch|çift kavrama|otomatik şanzıman)\b", re.I)
_MANUAL_ONLY_RE = re.compile(
    r"\b(manual gearbox|manuel şanzıman|clutch pedal|debriyaj pedal)\b", re.I)


def _compat_conditions(claim: dict, part_codes: set[str],
                       spanned: dict[str, set] | None = None) -> list[dict]:
    """Turn a claim's own text into the constraints it implies.

    `spanned` says which attribute values the part is actually fitted across,
    and it suppresses a gate that the catalog itself contradicts. A gearbox
    shared between petrol and diesel cars spans both fuels, so a claim about it
    that happens to name a petrol engine code is telling you which car the
    *source* discussed, not which cars have the gearbox. Applying a fuel gate
    there hides a real transmission fault from half the cars that have it —
    which is exactly what it did before this check existed.

    Deriving the span from fitment rather than listing the exceptions is the
    scalability principle: a new shared part is covered the moment its fitment
    rows exist, with nothing to remember to update.
    """
    text = f"{claim.get('title', '')} {claim.get('rationale', '')}"
    spanned = spanned or {}
    out = []

    diesel, petrol = bool(_DIESEL_RE.search(text)), bool(_PETROL_RE.search(text))
    if diesel and not petrol:
        out.append({"key": "fuel", "op": "eq", "value": "diesel"})
    elif petrol and not diesel:
        out.append({"key": "fuel", "op": "eq", "value": "petrol"})

    if _EV_HYBRID_RE.search(text):
        out.append({"key": "fuel", "op": "in", "value": "hybrid,electric"})

    awd, rwd = bool(_AWD_RE.search(text)), bool(_RWD_RE.search(text))
    if awd and not rwd:
        out.append({"key": "drivetrain", "op": "eq", "value": "awd"})
    elif rwd and not awd:
        out.append({"key": "drivetrain", "op": "eq", "value": "rwd"})

    if _SCR_RE.search(text):
        out.append({"key": "aftertreatment", "op": "eq", "value": "scr"})

    # A claim naming specific gearbox codes belongs only to those gearboxes.
    # The code list is derived from the part catalog, never hand-written — a new
    # gearbox is covered the moment its part file exists.
    mentioned = sorted(c for c in part_codes
                       if re.search(rf"\b{re.escape(c)}\b", text, re.I))
    if mentioned:
        out.append({"key": "transmission_code", "op": "in", "value": ",".join(mentioned)})
    elif _AUTO_ONLY_RE.search(text):
        out.append({"key": "transmission", "op": "eq", "value": "automatic"})
    elif _MANUAL_ONLY_RE.search(text):
        out.append({"key": "transmission", "op": "eq", "value": "manual"})

    kept = []
    for cond in out:
        values = spanned.get(cond["key"])
        demanded = {v.strip() for v in str(cond["value"]).split(",")}
        if values and len(values) > 1 and (values & demanded):
            # The part is fitted across several values of this attribute AND the
            # gate demands one of them, so the claim's text signal is telling us
            # which car the source discussed rather than which cars have the
            # part. Drop the gate — this is the shared-gearbox case.
            continue
        # If the demanded value is OUTSIDE the span entirely, keep the gate. An
        # E-Tech hybrid claim on a parts file fitted only to petrol and diesel
        # cars is not a shared-part signal; it is a claim about hardware none of
        # them has, and suppressing the gate would rank it first on a diesel.
        cond["weight"] = 1.0
        cond["on_missing"] = "ignore"
        kept.append(cond)
    return kept


def _conditions_from(claim: dict) -> list[dict]:
    """Every gate the old claim row carried, as condition rows.

    `weight` values mirror the old serving path's treatment of an unstated
    value: present but less certain, never hidden and never assumed.
    """
    out = []
    applies = claim.get("applies_when") or {}

    if applies.get("min_mileage_km") is not None:
        out.append({"key": "usage_km", "op": "gte",
                    "value": applies["min_mileage_km"], "weight": 0.7})
    if applies.get("max_mileage_km") is not None:
        out.append({"key": "usage_km", "op": "lte",
                    "value": applies["max_mileage_km"], "weight": 0.7})
    if applies.get("min_age_years") is not None:
        out.append({"key": "age_years", "op": "gte",
                    "value": applies["min_age_years"], "weight": 0.8})
    if applies.get("applies_year_from") is not None:
        out.append({"key": "build_year", "op": "gte",
                    "value": applies["applies_year_from"], "weight": 0.8})
    if applies.get("applies_year_to") is not None:
        out.append({"key": "build_year", "op": "lte",
                    "value": applies["applies_year_to"], "weight": 0.8})

    for tag in claim.get("requires_equipment") or []:
        out.append({"key": "equipment", "op": "has", "value": tag, "weight": 0.6})

    maintenance = claim.get("maintenance") or {}
    if maintenance.get("interval_km"):
        out.append({"key": "usage_km", "op": "interval",
                    "value": maintenance["interval_km"], "weight": 0.8})
    if maintenance.get("interval_years"):
        out.append({"key": "age_years", "op": "interval",
                    "value": maintenance["interval_years"], "weight": 0.8})
    if maintenance.get("evidence_keywords"):
        # Due UNLESS the ad proves otherwise. Silence is the signal, so the
        # condition holds precisely when the description does not mention the
        # work — and an absent description must still serve the claim.
        out.append({"key": "free_text", "op": "not_mentions",
                    "value": ",".join(maintenance["evidence_keywords"]),
                    "weight": 1.0, "on_missing": "open"})

    return out


def _part_spans() -> dict[str, dict[str, set]]:
    """part code -> {attribute: set of values across the cars fitted with it}.

    A part fitted only to diesels spans one fuel; a gearbox shared across the
    range spans several. That difference decides whether a text-derived
    compatibility gate is trustworthy for the part's claims.
    """
    variants = {}
    for path in sorted((DATA / "variants").glob("*.yaml")):
        for row in _yaml(path, []) or []:
            variants[row["id"]] = row

    spans: dict[str, dict[str, set]] = {}
    for path in sorted((DATA / "fitment").glob("*.yaml")):
        for row in _yaml(path, []) or []:
            variant = variants.get(row.get("variant_id", ""))
            if not variant:
                continue
            for key in FITMENT_KEYS:
                code = row.get(key)
                if not code or code in PSEUDO_PART_CODES:
                    continue
                bucket = spans.setdefault(code, {})
                for attribute in ("fuel", "drivetrain", "aftertreatment",
                                  "transmission", "transmission_code"):
                    if variant.get(attribute):
                        bucket.setdefault(attribute, set()).add(variant[attribute])
    return spans


def build(out_path: Path) -> tuple[Path, dict]:
    manifest = tomllib.loads((PACK_ROOT / "pack.toml").read_text(encoding="utf-8"))
    pack_id = manifest["pack"]["id"]
    identity_keys = manifest["identity"]
    status_confidence = manifest["status_confidence"]

    components = {c["id"]: c for c in
                  (_yaml(CATALOG / "components.yaml", {}) or {}).get("components", [])}
    tier_cfg = _yaml(TRUST / "source_tiers.yaml", {}) or {}

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    conn = connect(out_path)

    # Gearbox codes, derived from the part catalog rather than hand-listed, so a
    # new gearbox is covered the moment its part file exists.
    transmission_codes = {
        (_yaml(p, {}) or {}).get("part_id")
        for p in (DATA / "parts" / "transmission").glob("*.yaml")
    } - {None}

    row_ids: list[str] = []
    stats = Counter()
    id_map: dict[str, str] = {}     # legacy variant_id -> subject_id
    part_subjects: dict[str, str] = {}

    with conn:
        for term in _vocabulary():
            conn.execute(
                "INSERT OR REPLACE INTO terms (term_id, pack_id, role, datatype,"
                " unit, parent_id, label_json, match_json) VALUES (?,?,?,?,?,?,?,?)",
                (term["term_id"], pack_id, term.get("role", "attribute"),
                 term.get("datatype", "text"), term.get("unit", ""),
                 term.get("parent", ""),
                 yaml.safe_dump(term.get("label", {}), allow_unicode=True),
                 yaml.safe_dump(term.get("match", {}), allow_unicode=True)))
            row_ids.append(f"term:{term['term_id']}")
            for alias in term.get("aliases") or []:
                conn.execute("INSERT OR IGNORE INTO term_aliases VALUES (?,?,?,?)",
                             (term["term_id"], pack_id, alias, ""))
                row_ids.append(f"term_alias:{term['term_id']}:{alias}")
            stats["terms"] += 1

        # ── variants -> product subjects ─────────────────────────────────
        numeric_keys = {"displacement_cc", "power_min_hp", "power_max_hp"}
        for path in sorted((DATA / "variants").glob("*.yaml")):
            for variant in _yaml(path, []) or []:
                if variant.get("draft"):
                    stats["variants_skipped_draft"] += 1
                    continue

                identity = _identity_of(variant, identity_keys["product"])
                subject_id = ids.subject_id("product", identity)
                id_map[variant["id"]] = subject_id
                conn.execute("INSERT OR IGNORE INTO subjects VALUES (?,?,?,?)",
                             (subject_id, pack_id, "product", _label(variant)))
                row_ids.append(subject_id)
                stats["variants"] += 1

                for key, value in variant.items():
                    if key in {"id", "year_from", "year_to", "draft", "notes"}:
                        continue
                    if value in (None, ""):
                        continue
                    attribute_id = ids.attribute_id(subject_id, key, value)
                    conn.execute(
                        "INSERT OR IGNORE INTO attributes (attribute_id, pack_id,"
                        " subject_id, key, value_text, value_num, unit, valid_from,"
                        " valid_to, is_identity, confidence)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (attribute_id, pack_id, subject_id, key, str(value),
                         _num(value) if key in numeric_keys else None, "", "", "",
                         1 if key in identity_keys["product"] else 0, None))
                    row_ids.append(attribute_id)

                # One row with bounds, not two attributes: a production run is
                # a single fact, and bounds are what a listing year is tested
                # against without the engine knowing what a model year is.
                if variant.get("year_from"):
                    valid_from = str(variant["year_from"])
                    valid_to = str(variant.get("year_to") or "")
                    attribute_id = ids.attribute_id(
                        subject_id, "build_year", "production",
                        valid_from=valid_from, valid_to=valid_to)
                    conn.execute(
                        "INSERT OR IGNORE INTO attributes (attribute_id, pack_id,"
                        " subject_id, key, value_text, value_num, unit, valid_from,"
                        " valid_to, is_identity, confidence)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (attribute_id, pack_id, subject_id, "build_year",
                         f"{valid_from}-{valid_to or 'present'}", None, "",
                         valid_from, valid_to, 0, None))
                    row_ids.append(attribute_id)

        # Which attribute values each part is actually fitted across. Derived
        # from fitment + variants, never hand-listed.
        part_spans = _part_spans()

        # ── parts -> part subjects + claims ──────────────────────────────
        for path in sorted((DATA / "parts").rglob("*.yaml")):
            part = _yaml(path, {}) or {}
            part_code = part.get("part_id")
            if not part_code:
                continue

            subject_id = ids.subject_id("part", {"part_code": part_code})
            part_subjects[part_code] = subject_id
            conn.execute("INSERT OR IGNORE INTO subjects VALUES (?,?,?,?)",
                         (subject_id, pack_id, "part",
                          part.get("display_name", part_code)))
            row_ids.append(subject_id)
            stats["parts"] += 1

            for key in ("part_type", "manufacturer", "code_family"):
                if part.get(key):
                    attribute_id = ids.attribute_id(subject_id, key, part[key])
                    conn.execute(
                        "INSERT OR IGNORE INTO attributes (attribute_id, pack_id,"
                        " subject_id, key, value_text, value_num, unit, valid_from,"
                        " valid_to, is_identity, confidence)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (attribute_id, pack_id, subject_id, key, str(part[key]),
                         None, "", "", "", 0, None))
                    row_ids.append(attribute_id)

            for alias in part.get("known_also_as") or []:
                conn.execute("INSERT OR IGNORE INTO subject_aliases VALUES (?,?,?,?,?)",
                             (subject_id, pack_id, alias, "", "attribution_safe"))
                row_ids.append(f"subject_alias:{subject_id}:{alias}")

            for claim in part.get("claims") or []:
                confidence = status_confidence.get(claim.get("status", "review"), 0.6)
                if confidence <= 0:
                    stats["claims_skipped_by_status"] += 1
                    continue

                component = components.get(claim.get("component_id") or "", {})
                title = claim.get("title", "")
                claim_id = ids.claim_id(subject_id, claim.get("kind", "known_issue"),
                                        claim.get("domain", "general"), title)

                conn.execute(
                    "INSERT OR IGNORE INTO claims (claim_id, pack_id, subject_id,"
                    " kind, domain, severity, consequence, detection, component,"
                    " subsystem, author_confidence, created_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (claim_id, pack_id, subject_id, claim.get("kind", "known_issue"),
                     claim.get("domain", "general"), claim.get("severity", "medium"),
                     claim.get("consequence", ""), claim.get("detection", ""),
                     claim.get("component_id", ""), component.get("subsystem", ""),
                     float(claim.get("confidence", 0.6)) * confidence, _now()))
                row_ids.append(claim_id)
                stats["claims"] += 1

                for lang, tkey, bkey, akey in (
                        ("en", "title", "rationale", "inspection_advice"),
                        ("tr", "title_tr", "rationale_tr", "inspection_advice_tr")):
                    text = claim.get(tkey)
                    if not text:
                        continue
                    conn.execute(
                        "INSERT OR IGNORE INTO claim_text VALUES (?,?,?,?,?,?)",
                        (claim_id, pack_id, lang, text, claim.get(bkey, ""),
                         claim.get(akey, "")))
                    row_ids.append(f"text:{claim_id}:{lang}")
                    stats[f"text_{lang}"] += 1

                conditions = (_conditions_from(claim)
                              + _compat_conditions(claim, transmission_codes,
                                                   part_spans.get(part_code, {})))
                for seq, cond in enumerate(conditions):
                    conn.execute(
                        "INSERT OR REPLACE INTO claim_conditions (claim_id, pack_id,"
                        " seq, key, op, value_text, value_num, on_missing, weight)"
                        " VALUES (?,?,?,?,?,?,?,?,?)",
                        (claim_id, pack_id, seq, cond["key"], cond["op"],
                         str(cond["value"]), _num(cond["value"]),
                         cond.get("on_missing", "open"), cond["weight"]))
                    row_ids.append(f"cond:{claim_id}:{seq}")
                    stats["conditions"] += 1

                for source in claim.get("sources") or []:
                    url = source.get("source_url", "")
                    quote = source.get("quote", "")
                    if not (url or quote):
                        continue
                    source_id = ids.source_id(url=url, text=quote)
                    conn.execute(
                        "INSERT OR IGNORE INTO sources (source_id, pack_id, url,"
                        " domain, site_or_channel, title, lang, source_type,"
                        " published_at, retrieved_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (source_id, pack_id, url, source.get("source_domain", ""),
                         source.get("site_or_channel", ""), source.get("title") or "",
                         "", "page", "", ""))
                    row_ids.append(source_id)

                    evidence_id = ids.evidence_id(source_id, quote)
                    conn.execute(
                        "INSERT OR IGNORE INTO evidence (evidence_id, pack_id,"
                        " claim_id, source_id, quote, locator, stance, independent)"
                        " VALUES (?,?,?,?,?,?,?,?)",
                        (evidence_id, pack_id, claim_id, source_id, quote,
                         str(source.get("timestamp_s") or ""), "supports",
                         1 if source.get("independent", True) else 0))
                    row_ids.append(evidence_id)
                    stats["evidence"] += 1

        # ── fitment -> relations ─────────────────────────────────────────
        for path in sorted((DATA / "fitment").glob("*.yaml")):
            for row in _yaml(path, []) or []:
                subject_id = id_map.get(row.get("variant_id", ""))
                if not subject_id:
                    stats["fitment_skipped_unknown_variant"] += 1
                    continue
                for key, part_type in FITMENT_KEYS.items():
                    code = row.get(key)
                    if not code or code in PSEUDO_PART_CODES:
                        continue
                    target = part_subjects.get(code)
                    if target is None:
                        # Fail open and count it: a missing stub is a coverage
                        # finding for the remediation loop, not a build failure.
                        stats["fitment_missing_part_stub"] += 1
                        continue
                    relation_id = ids.relation_id(subject_id, "part_of", target)
                    conn.execute(
                        "INSERT OR IGNORE INTO relations VALUES (?,?,?,?,?,?)",
                        (relation_id, pack_id, subject_id, "part_of", target,
                         f"Part fitment: {code} ({part_type})"))
                    row_ids.append(relation_id)
                    stats["relations"] += 1

        # ── research assets ──────────────────────────────────────────────
        # The value principle used to be a string literal inside
        # knowledge/ledger/verdict.py, which meant the question "what is worth
        # keeping?" was answered once, in Python, for every product Kriko would
        # ever know about. It belongs to the category.
        for name, kind in (("research/principle.md", "principle"),
                           ("research/templates.yaml", "templates")):
            path = PACK_ROOT / name
            if path.exists():
                conn.execute("INSERT OR REPLACE INTO pack_assets VALUES (?,?,?,?)",
                             (pack_id, name, kind, path.read_text(encoding="utf-8")))
                row_ids.append(f"asset:{name}")
                stats["assets"] += 1

        for path in sorted((PACK_ROOT / "adapters").glob("*.json")):
            conn.execute("INSERT OR REPLACE INTO pack_assets VALUES (?,?,?,?)",
                         (pack_id, f"adapters/{path.name}", "adapter",
                          path.read_text(encoding="utf-8")))
            row_ids.append(f"asset:adapters/{path.name}")
            stats["assets"] += 1

        # ── source tiers ─────────────────────────────────────────────────
        for tier, cfg in (tier_cfg.get("tiers") or {}).items():
            conn.execute("INSERT OR REPLACE INTO tier_trust VALUES (?,?,?)",
                         (tier, pack_id, float(cfg["trust"])))
            row_ids.append(f"tier_trust:{tier}")

        for domain, cfg in (tier_cfg.get("domains") or {}).items():
            conn.execute("INSERT OR REPLACE INTO source_tiers VALUES (?,?,?,?)",
                         (domain, pack_id, cfg["tier"], ""))
            row_ids.append(f"tier:{domain}")
            stats["source_tiers"] += 1

        # Contains-rules and the catch-all default become patterns, so the pack
        # can say "anything with 'forum.' in it is user-generated" without
        # enumerating the internet.
        for rule in tier_cfg.get("rules") or []:
            for fragment in rule.get("domain_contains") or []:
                conn.execute("INSERT OR REPLACE INTO source_tiers VALUES (?,?,?,?)",
                             (f"*{fragment}*", pack_id, rule["tier"],
                              "contains-rule"))
                row_ids.append(f"tier:*{fragment}*")
        if tier_cfg.get("default"):
            conn.execute("INSERT OR REPLACE INTO source_tiers VALUES (?,?,?,?)",
                         ("*", pack_id, tier_cfg["default"], "pack default"))
            row_ids.append("tier:*")

        conn.execute(
            "INSERT OR REPLACE INTO packs (pack_id, name, version, schema_version,"
            " built_at, publisher, license, origin_url, content_digest,"
            " manifest_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pack_id, manifest["pack"]["name"], manifest["pack"]["version"],
             SCHEMA_VERSION, _now(), manifest["pack"].get("publisher", ""),
             manifest["pack"].get("license", ""), manifest["pack"].get("origin", ""),
             ids.content_digest(row_ids),
             yaml.safe_dump(manifest, allow_unicode=True)))

    conn.close()
    return out_path, {"stats": dict(stats), "id_map": id_map}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="packs.cars.build")
    parser.add_argument("--out", default="dist/cars.kpack")
    args = parser.parse_args(argv)

    out, report = build(Path(args.out))
    print(f"built {out}")
    for key, value in sorted(report["stats"].items()):
        print(f"  {key:34} {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
