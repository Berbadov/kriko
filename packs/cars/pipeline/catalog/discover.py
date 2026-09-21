"""discover.py — catalog bootstrap: given a make + model, enumerate all engine
and transmission codes from Wikipedia's structured infobox.

This is the first step in the part-centric research pipeline. You must know what
parts a model has before you can search for issues with those specific parts. This
module fetches the Wikipedia **wikitext** (not the plain-text extract) to access the
{{Infobox automobile}} template which contains structured engine and transmission data.

Why wikitext, not extracts?
  The MediaWiki `extracts` API strips tables and infoboxes to plain prose. Car model
  articles keep their engine specs in the infobox (``| engine = {{ubl | ... }}``)
  and in specification tables — both are lost in plain-text extraction. The raw
  wikitext preserves this structure. Engine codes appear in italic markup:
    ''[[link|H5Ht]]''  →  code = H5H
    ''[[link|K9K]]''   →  code = K9K
  Fuel type labels appear in bold:  '''Petrol:'''  /  '''Diesel:'''
  This is parsed deterministically — no LLM involved.

Scalability: works for any Wikipedia article by adding one row to
  packs/cars/pipeline/catalog/wikipedia_articles.yaml — no Python edit. The parser
  is model-agnostic.

Usage:
    python -m packs.cars.pipeline.catalog.discover --make renault --model megane_4
    python -m packs.cars.pipeline.catalog.discover --make volkswagen --model golf_7
    python -m packs.cars.pipeline.catalog.discover --make toyota --model rav4_5 --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

import httpx
import yaml
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

from packs.cars.pipeline.paths import REPO_ROOT
FITMENT_DIR = REPO_ROOT / "packs" / "cars" / "data" / "fitment"
VARIANTS_DIR = REPO_ROOT / "packs" / "cars" / "data" / "variants"
CACHE_DIR = Path(__file__).parent / "cache"

_HEADERS = {"User-Agent": "KrikoBot/1.0 (automotive reliability research; +https://github.com/kriko)"}
_TIMEOUT = 20

# Generation ordinals for section heading lookup
_ORDINALS = {
    1: ["first", "mk1", "mk i", "i ("],
    2: ["second", "mk2", "mk ii", "ii ("],
    3: ["third", "mk3", "mk iii", "iii ("],
    4: ["fourth", "mk4", "mk iv", "iv ("],
    5: ["fifth", "mk5", "mk v", "v ("],
    6: ["sixth", "mk6", "mk vi", "vi ("],
    7: ["seventh", "mk7", "mk vii", "vii ("],
    8: ["eighth", "mk8", "mk viii", "viii ("],
}

# Wikipedia article titles per (make, model).
# Key: lowercase "{make}_{model}" — value: Wikipedia article title to fetch.
# The generation is extracted from the model suffix (e.g. megane_4 → 4th gen section).
_BOOTSTRAP_PATH = Path(__file__).resolve().parent / "wikipedia_articles.yaml"


@lru_cache(maxsize=1)
def _bootstrap() -> dict:
    """Wikipedia article titles + engine-code aliases, read off YAML.

    Kept as data rather than a Python dict because onboarding a model must
    never mean editing Python (CLAUDE.md scalability principle). It cannot be
    derived from the catalog the way catalog_code_manufacturers() is: discover
    runs before the model has a catalog row, and exists to create one.
    """
    with open(_BOOTSTRAP_PATH, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return {
        "articles": data.get("articles") or {},
        "engine_aliases": data.get("engine_aliases") or {},
    }


def wikipedia_article_title(key: str) -> str | None:
    """Article title for a catalog key, or None to fall back to a guess."""
    return _bootstrap()["articles"].get(key)


def engine_alias(code: str) -> str | None:
    """Market code for a Wikipedia-printed engine code, if it differs."""
    return _bootstrap()["engine_aliases"].get(code)


# ── Data types ────────────────────────────────────────────────────────────────

class PartSpec(NamedTuple):
    engine_code: str          # raw code from infobox (e.g. "K9K", "H5Ft")
    engine_family: str        # normalised lowercase research key (e.g. "k9k", "h5h")
    fuel: str                 # "diesel" | "petrol" | "hybrid" | "electric" | "unknown"
    displacement_cc: int | None
    transmission_codes: list[str]  # e.g. ["manual", "edc"]
    notes: str


class ModelCatalog(NamedTuple):
    make: str
    model: str
    engines: list[PartSpec]
    transmissions: list[str]  # all transmission codes for this generation
    source: str               # "wikitext" | "cache" | "manual"


# ── Wikipedia wikitext fetching ───────────────────────────────────────────────

def _fetch_wikitext(article_title: str) -> str | None:
    """Return raw wikitext for a Wikipedia article by title."""
    try:
        resp = httpx.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "prop": "revisions",
                "titles": article_title,
                "rvslots": "main",
                "rvprop": "content",
                "format": "json",
            },
            headers=_HEADERS,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        pages = resp.json().get("query", {}).get("pages", {})
        page = next(iter(pages.values()))
        if "revisions" not in page:
            log.warning("Wikipedia: no revisions for %r", article_title)
            return None
        return page["revisions"][0]["slots"]["main"]["*"]
    except Exception as exc:
        log.warning("Wikipedia wikitext fetch failed for %r: %s", article_title, exc)
        return None


def _find_generation_section(wikitext: str, generation: int) -> str | None:
    """Return the portion of wikitext for the specified generation.

    Looks specifically within section heading lines (== ... ==) for ordinal words
    (Fourth, Mk4, IV). Returns text from that heading to the next same-level heading.
    Falls back to full article if no generation-specific heading is found (single-gen
    articles like "Ford Focus (third generation)").
    """
    ordinals = _ORDINALS.get(generation, [])

    section_start = -1
    section_depth = 2

    for line_m in re.finditer(r'^(=+)\s*(.+?)\s*\1\s*$', wikitext, re.MULTILINE):
        heading_text = line_m.group(2).lower()
        depth = len(line_m.group(1))
        for ordinal in ordinals:
            if ordinal in heading_text:
                section_start = line_m.start()
                section_depth = depth
                break
        if section_start >= 0:
            break

    if section_start < 0:
        log.info("No generation heading found; using full article")
        return wikitext

    section_text = wikitext[section_start:]

    # Find the next heading at the same depth or higher (fewer = signs)
    end_pattern = re.compile(r'\n={1,' + str(section_depth) + r'}[^=]')
    end_m = end_pattern.search(section_text, 1)
    if end_m:
        return section_text[:end_m.start()]
    return section_text


# ── Infobox field extraction (brace-counting) ─────────────────────────────────

def _extract_infobox_field(wikitext: str, field: str) -> str | None:
    """Extract a named field value from a MediaWiki infobox, handling nested {{...}}.

    Wikipedia infoboxes use template syntax; naive regex fails on nested braces.
    This brace-counter correctly finds the end of the field value.
    """
    pattern = re.compile(r'\|\s*' + re.escape(field) + r'\s*=\s*', re.IGNORECASE)
    m = pattern.search(wikitext)
    if not m:
        return None

    start = m.end()
    depth = 0
    i = start
    while i < len(wikitext):
        two = wikitext[i:i + 2]
        if two == "{{":
            depth += 1
            i += 2
        elif two == "}}":
            if depth > 0:
                depth -= 1
                i += 2
            else:
                break
        elif wikitext[i] == "|" and depth == 0:
            break
        else:
            i += 1

    return wikitext[start:i].strip()


# ── Engine code parsing ───────────────────────────────────────────────────────

def _normalise_engine_code(raw_code: str) -> tuple[str, str]:
    """Return (display_code, engine_family) from a raw infobox engine code.

    Strips descriptor suffixes (dCi, biturbo) and applies known aliases.
    H5Ft → ('H5F', 'h5f'),  K9K → ('K9K', 'k9k'),  R9M dCi → ('R9M', 'r9m')
    """
    # Strip common trailing descriptors
    code = re.sub(r'\s+(dci|tce|sce|phev|biturbo|turbo|hybrid).*$', '', raw_code,
                  flags=re.IGNORECASE).strip()
    family = engine_alias(code.lower()) or code.lower()
    return code, family


def _parse_engine_field(field: str) -> list[dict]:
    """Parse engine codes and fuel types from an infobox ``| engine = ...`` value.

    Returns list of dicts with keys: engine_code, engine_family, fuel, displacement_cc.
    """
    current_fuel = "unknown"
    results: list[dict] = []
    seen_codes: set[str] = set()

    for line in field.splitlines():
        line = line.strip().lstrip("|").strip()
        if not line or line in ("{", "}", "{{ubl", "}}"):
            continue

        # ── Fuel type label (bold text ending in colon) ──────────────────────
        # Patterns: '''Petrol:'''  '''Diesel:'''  '''Petrol plug-in hybrid:'''
        if "'''" in line:
            lw = line.lower()
            if "diesel" in lw:
                current_fuel = "diesel"
            elif "plug-in hybrid" in lw or "phev" in lw:
                current_fuel = "hybrid"
            elif "petrol" in lw or "gasoline" in lw:
                current_fuel = "petrol"
            elif "electric" in lw:
                current_fuel = "electric"
            continue

        # ── Skip lines with no displacement (not an engine spec line) ─────────
        disp_m = re.search(r'([\d.]+)\s*(?:&nbsp;)?L\b', line)
        if not disp_m:
            continue
        cc = int(float(disp_m.group(1)) * 1000)

        # ── Engine code: from italic ''...'' or bare wikilink [[...|CODE]] ───
        # Priority 1: italic markup  ''[[link|CODE]]'' or ''CODE''
        candidate_codes: list[str] = []
        for span in re.findall(r"''(.+?)''", line):
            link_m = re.search(r'\[\[.+?\|([^\]]+)\]\]', span)
            candidate_codes.append(link_m.group(1).strip() if link_m else span.strip())

        # Priority 2: bare wikilink on a displacement line (no italic wrapper)
        # e.g.  1.7 L [[Engine article|R9N]] description
        # Only accept all-uppercase codes (K9K, R9N, EA211) to avoid brand names
        # like "BluedCi" or "AdBlue" that share the wikilink format.
        if not candidate_codes:
            for bare_m in re.finditer(r'\[\[[^\]]+?\|([A-Z][A-Z0-9]{1,5})\]\]', line):
                candidate_codes.append(bare_m.group(1).strip())

        for raw_code in candidate_codes:
            # Filter: engine codes are short alphanumeric + optional descriptor
            if not re.match(r'^[A-Za-z][A-Za-z0-9]{1,6}(\s+(dCi|tCe|sCe|biturbo))?$',
                            raw_code, re.IGNORECASE):
                continue

            display_code, family = _normalise_engine_code(raw_code)

            if display_code in seen_codes:
                continue
            seen_codes.add(display_code)

            results.append({
                "engine_code": display_code,
                "engine_family": family,
                "fuel": current_fuel,
                "displacement_cc": cc,
            })

    return results


def _parse_transmission_field(field: str) -> list[str]:
    """Parse transmission type codes from an infobox ``| transmission = ...`` value.

    Returns a list of lowercase short codes: "manual", "edc", "dq200", "cvt", etc.
    """
    codes: list[str] = []
    seen: set[str] = set()

    for line in field.splitlines():
        lw = line.lower()

        # Specific DCT/DSG codes — check before generic "automatic"
        for code in ["dq200", "dq250", "dq381", "dq500", "dq511"]:
            if code in lw and code not in seen:
                codes.append(code)
                seen.add(code)
                break

        if "edc" in lw and "edc" not in seen:
            codes.append("edc")
            seen.add("edc")
        elif "dsg" in lw and "dsg" not in seen:
            codes.append("dsg")
            seen.add("dsg")
        elif "dual-clutch" in lw and "edc" not in seen and "dsg" not in seen:
            codes.append("dct")
            seen.add("dct")

        if "cvt" in lw and "cvt" not in seen:
            codes.append("cvt")
            seen.add("cvt")

        if "manual" in lw and "manual" not in seen:
            codes.append("manual")
            seen.add("manual")

    return codes


# ── Cache ─────────────────────────────────────────────────────────────────────

def _cache_path(make: str, model: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"catalog_{make}_{model}.json"


def _load_cache(make: str, model: str) -> dict | None:
    p = _cache_path(make, model)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _save_cache(make: str, model: str, data: dict) -> None:
    _cache_path(make, model).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Fitment YAML update ───────────────────────────────────────────────────────

def _match_specs_to_variants(
    specs: list[PartSpec],
    all_tx_codes: list[str],
    make: str,
    model: str,
) -> list[dict]:
    """Match discovered part specs to existing variant_ids in the variants YAML.

    For each variant, finds the PartSpec that best matches engine_code / power / fuel,
    then picks the correct transmission_code for that variant.
    Returns fitment rows: {variant_id, engine_family, transmission_code}.
    """
    variants_path = VARIANTS_DIR / f"{make}_{model}.yaml"
    if not variants_path.exists():
        log.warning("Variants YAML not found: %s", variants_path)
        return []

    variants: list[dict] = yaml.safe_load(variants_path.read_text(encoding="utf-8")) or []
    fitment_rows: list[dict] = []

    for v in variants:
        vid = v.get("id", "")
        v_fuel = (v.get("fuel") or "").lower()
        v_ec = (v.get("engine_code") or "").upper()
        v_ef = (v.get("engine_family") or "").lower()
        v_trans_code = (v.get("transmission_code") or "")
        v_trans = (v.get("transmission") or "").lower()

        # If variant already has engine_family from hand-curation, trust it
        if v_ef and v_trans_code:
            row: dict = {
                "variant_id": vid,
                "engine_family": v_ef,
                "transmission_code": v_trans_code,
            }
            for extra in ("cooling_code", "electrical_code", "body_code"):
                if v.get(extra):
                    row[extra] = v[extra]
            fitment_rows.append(row)
            continue

        # Find best matching PartSpec
        best: PartSpec | None = None
        best_score = -1

        for spec in specs:
            score = 0
            # Engine code match (exact or family)
            spec_ec = spec.engine_code.upper()
            spec_ef = spec.engine_family.upper()
            if v_ec and (v_ec == spec_ec or v_ec == spec_ef or v_ef.upper() == spec_ef):
                score += 10
            elif v_ec and (spec_ec in v_ec or v_ec in spec_ec):
                score += 5
            # Fuel match
            if v_fuel and spec.fuel and (v_fuel in spec.fuel or spec.fuel in v_fuel):
                score += 3
            # CC match (within ±200cc)
            v_cc = v.get("displacement_cc") or 0
            if v_cc and spec.displacement_cc and abs(v_cc - spec.displacement_cc) <= 200:
                score += 2

            if score > best_score:
                best_score = score
                best = spec

        if best is None or best_score < 3:
            log.warning("No spec match for variant %s (score=%d)", vid, best_score)
            continue

        # Determine transmission_code: prefer hand-curated variant field
        if v_trans_code:
            tx_code = v_trans_code
        elif "automatic" in v_trans or "edc" in v_trans or "dsg" in v_trans:
            # Pick first non-manual code from this spec or global list
            non_manual = [t for t in (best.transmission_codes or all_tx_codes) if t != "manual"]
            tx_code = non_manual[0] if non_manual else "automatic"
        else:
            tx_code = "manual"

        matched_row: dict = {
            "variant_id": vid,
            "engine_family": best.engine_family,
            "transmission_code": tx_code,
        }
        for extra in ("cooling_code", "electrical_code", "body_code"):
            if v.get(extra):
                matched_row[extra] = v[extra]
        fitment_rows.append(matched_row)

    return fitment_rows


# ── Public API ────────────────────────────────────────────────────────────────

def discover(
    make: str,
    model: str,
    force: bool = False,
    dry_run: bool = False,
) -> ModelCatalog:
    """Discover all engine and transmission codes for a car model via Wikipedia wikitext.

    Fetches the Wikipedia article, finds the generation-specific infobox,
    parses engine codes deterministically from italic markup, caches result.
    """
    make = make.lower()
    model = model.lower()
    key = f"{make}_{model}"

    cached = None if force else _load_cache(make, model)
    if cached is not None:
        print(f"  Loaded catalog from cache ({len(cached.get('engines', []))} engine variants)")
        engines = [PartSpec(**e) for e in cached["engines"]]
        transmissions = cached.get("transmissions", [])
        return ModelCatalog(make=make, model=model, engines=engines,
                            transmissions=transmissions, source="cache")

    article_title = wikipedia_article_title(key)
    if not article_title:
        # Generic fallback: construct from make + model name
        model_name = re.sub(r'_\d+$', '', model).replace('_', ' ').title()
        article_title = f"{make.title()} {model_name}"
        print(f"  No article mapping for {key!r} — trying {article_title!r}")

    print(f"  Fetching Wikipedia wikitext: {article_title!r}")
    wikitext = _fetch_wikitext(article_title)
    if not wikitext:
        print("  Failed to fetch wikitext.")
        return ModelCatalog(make=make, model=model, engines=[], transmissions=[], source="wikipedia")

    # Determine generation number from model key (e.g. megane_4 → 4)
    gen_m = re.search(r'_(\d+)$', model)
    generation = int(gen_m.group(1)) if gen_m else 0

    # Skip generation-section search for articles that cover only one generation
    # (i.e. the article title already includes the generation, e.g. "Golf Mk7")
    title_lower = article_title.lower()
    single_gen_article = any(
        kw in title_lower
        for kw in ["mk7", "mk8", "mk6", "mk5", "third generation", "fourth generation",
                   "fifth generation", "e210", "e300"]
    )

    if generation and not single_gen_article:
        print(f"  Finding generation {generation} section…")
        section = _find_generation_section(wikitext, generation)
    else:
        print("  Single-generation article — using full wikitext.")
        section = wikitext

    if not section:
        print("  Could not find generation section.")
        return ModelCatalog(make=make, model=model, engines=[], transmissions=[], source="wikipedia")

    print(f"  Parsing infobox from {len(section):,}-char section…")
    engine_field = _extract_infobox_field(section, "engine")
    transmission_field = _extract_infobox_field(section, "transmission")

    if not engine_field:
        print("  No engine field found in infobox.")
        return ModelCatalog(make=make, model=model, engines=[], transmissions=[], source="wikipedia")

    raw_engines = _parse_engine_field(engine_field)
    all_tx_codes = _parse_transmission_field(transmission_field or "")

    print(f"  Found {len(raw_engines)} engine variant(s), transmissions: {all_tx_codes}")

    # Convert to PartSpec (transmission_codes per engine assigned at match time)
    specs = [
        PartSpec(
            engine_code=e["engine_code"],
            engine_family=e["engine_family"],
            fuel=e["fuel"],
            displacement_cc=e["displacement_cc"],
            transmission_codes=all_tx_codes,
            notes="",
        )
        for e in raw_engines
    ]

    if not dry_run:
        _save_cache(make, model, {
            "engines": [e._asdict() for e in specs],
            "transmissions": all_tx_codes,
        })

    return ModelCatalog(make=make, model=model, engines=specs,
                        transmissions=all_tx_codes, source="wikitext")


def write_variants_yaml(
    make: str, model: str, catalog: ModelCatalog, dry_run: bool = False
) -> list[dict]:
    """Scaffold packs/cars/data/variants/{make}_{model}.yaml from discovered engine
    codes and transmissions — closes docs/USAGE.md's onboarding Step 1, the one
    fully-manual step left in the 4-step flow (Step 3, fitment, already had an
    automated path via write_fitment_yaml() above; this is its counterpart).

    Wikipedia's infobox reliably gives engine code, fuel, and displacement, but
    NOT a precise per-market power (hp) figure or exact per-trim year range —
    inventing one here would be exactly the kind of fabricated car data this
    whole initiative exists to reduce (see CLAUDE.md, packs/cars/pipeline/extract.py).
    So every row is written with power_min_hp/power_max_hp/year_to left
    unset and a `draft: true` marker; the pack builder refuses to build draft
    rows into the servable DB. A human fills in real figures (manufacturer
    spec sheet, TecDoc) and removes the marker before this feeds the pipeline.

    Never overwrites an existing variants file (would blow away real hp/year
    data already filled in) — only writes when the file doesn't exist yet.
    """
    path = VARIANTS_DIR / f"{make}_{model}.yaml"
    if path.exists():
        print(f"  {path} already exists — not overwriting. Delete it first to rescaffold.")
        return []

    gen_m = re.search(r'_(\d+)$', model)
    base_model = model[:gen_m.start()] if gen_m else model
    generation = gen_m.group(1) if gen_m else None

    rows: list[dict] = []
    for spec in catalog.engines:
        tx_codes = spec.transmission_codes or ["manual"]
        for tx in tx_codes:
            vid = f"{model}_{spec.engine_family}" + (f"_{tx}" if tx != "manual" else "")
            row = {
                "id": vid,
                "make": make,
                "model": base_model,
                "engine_code": spec.engine_code,
                "engine_family": spec.engine_family,
                "fuel": spec.fuel,
                "displacement_cc": spec.displacement_cc,
                "transmission": "manual" if tx == "manual" else "automatic",
                "transmission_code": tx,
                "draft": True,
            }
            if generation:
                row["generation"] = generation
            rows.append(row)

    if dry_run:
        print(f"  DRY RUN — would write {len(rows)} draft variant row(s) to {path}")
        for r in rows:
            print(f"    {r['id']}: {r['engine_family']}/{r['transmission_code']} ({r['fuel']})")
        return rows

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(rows, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(
        f"  Wrote {len(rows)} DRAFT variant row(s) to {path} — fill in "
        f"power_min_hp/power_max_hp/year_from/year_to and remove 'draft: true' "
        f"before running write-fitment or syncing."
    )
    return rows


def write_fitment_yaml(
    make: str, model: str, catalog: ModelCatalog, dry_run: bool = False
) -> list[dict]:
    """Match catalog specs to existing variants and write/update fitment YAML."""
    fitment_rows = _match_specs_to_variants(
        catalog.engines, catalog.transmissions, make, model
    )
    if not fitment_rows:
        print("  No fitment rows generated.")
        return []

    path = FITMENT_DIR / f"{make}_{model}.yaml"
    if dry_run:
        print(f"  DRY RUN — would write {len(fitment_rows)} fitment rows to {path}")
        for r in fitment_rows:
            print(f"    {r['variant_id']}: engine_family={r['engine_family']}, tx={r['transmission_code']}")
        return fitment_rows

    # Merge with existing fitment — generated rows update existing ones (adds new
    # fields like cooling_code/electrical_code), but hand-curated extra keys are kept.
    existing: list[dict] = []
    if path.exists():
        existing = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    existing_map: dict[str, dict] = {r["variant_id"]: r for r in existing}

    updated = []
    new_count = 0
    for r in fitment_rows:
        if r["variant_id"] in existing_map:
            # Merge: generated row wins for its own keys; preserve any hand-curated extras
            merged = dict(existing_map[r["variant_id"]])
            merged.update(r)
            updated.append(merged)
        else:
            updated.append(r)
            new_count += 1

    path.write_text(yaml.dump(updated, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"  Wrote {len(updated)} fitment rows to {path} ({new_count} new).")
    return updated


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(
        description=(
            "Discover engine/transmission codes for a car model from Wikipedia infoboxes.\n"
            "The model key must match the variants YAML filename: renault_megane_4 → "
            "packs/cars/data/variants/renault_megane_4.yaml"
        )
    )
    parser.add_argument("--make", required=True, help="Make (e.g. renault, volkswagen)")
    parser.add_argument("--model", required=True,
                        help="Model key matching the variants YAML (e.g. megane_4, golf_7)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and parse but do not write any files")
    parser.add_argument("--force", action="store_true",
                        help="Ignore cache and re-fetch from Wikipedia")
    parser.add_argument("--write-variants", action="store_true",
                        help="Scaffold a draft variants YAML (Step 1) if one doesn't exist yet — "
                             "review and fill in power/year figures before using")
    parser.add_argument("--write-fitment", action="store_true",
                        help="Write/update the fitment YAML after matching to variants")
    args = parser.parse_args()

    catalog = discover(args.make, args.model, force=args.force, dry_run=args.dry_run)

    if not catalog.engines:
        print("No engine variants discovered.")
        return

    print(f"\nDiscovered {len(catalog.engines)} engine variant(s) for {args.make} {args.model}:")
    print(f"{'CODE':<10} {'FAMILY':<10} {'FUEL':<10} {'CC':>5}")
    print("-" * 40)
    for s in catalog.engines:
        print(f"{s.engine_code:<10} {s.engine_family:<10} {s.fuel:<10} {s.displacement_cc or '':>5}")

    print(f"\nAll transmission types: {catalog.transmissions}")

    # Unique research targets (filtered to Heavy/Medium parts per taxonomy)
    researchable_fuels = {"diesel", "petrol"}
    unique_families = sorted({s.engine_family for s in catalog.engines
                               if s.fuel in researchable_fuels})
    non_manual_tx = [t for t in catalog.transmissions if t != "manual" and t != "cvt"]

    print("\nResearch targets:")
    for fam in unique_families:
        fuel = next((s.fuel for s in catalog.engines if s.engine_family == fam), "")
        fuel_flag = f"--fuel {fuel}" if fuel else ""
        print(f"  python -m app.pipeline.ledger_run acquire --part {fam} --part-type engine {fuel_flag}")
    for tx in non_manual_tx:
        print(f"  python -m app.pipeline.ledger_run acquire --part {tx} --part-type transmission")

    if args.write_variants:
        print("\nScaffolding draft variants YAML…")
        write_variants_yaml(args.make, args.model, catalog, dry_run=args.dry_run)

    if args.write_fitment:
        print("\nWriting fitment YAML…")
        write_fitment_yaml(args.make, args.model, catalog, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
