"""process.py — run pending curated sources through the full knowledge pipeline.

Picks up every entry with status=pending (or no status) from the curated
YAML for the given make/model/gen, extracts claims, scores them, and writes
auto-verified claims to the backend claims YAML. Then reloads the DB.

Usage:
    python -m knowledge.process renault megane 4
    python -m knowledge.process toyota corolla e210 --dry-run
"""

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

REPO_ROOT   = Path(__file__).parent.parent
DATA_DIR    = REPO_ROOT / "backend" / "data"
CURATED_DIR = Path(__file__).parent / "sources" / "curated"
CACHE_DIR   = Path(__file__).parent / "cache"


def _cache_path(make: str, model: str, gen: str) -> Path:
    return CACHE_DIR / f"{make}_{model}_{gen}_candidates.json"


def _write_candidate_cache(make, model, gen, candidates) -> Path:
    """Persist extracted (claim, doc) pairs so gate-only re-runs cost zero
    extraction tokens and zero web fetches (see pipeline_postmortem #3)."""
    from knowledge.sources.base import Document

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "claim": claim.model_dump(),
            "doc": {
                "text": doc.text,
                "url": doc.url,
                "tier": doc.tier.value,
                "site_or_channel": doc.site_or_channel,
                "meta": doc.meta,
            },
        }
        for claim, doc in candidates
    ]
    assert all(isinstance(doc, Document) for _, doc in candidates)
    path = _cache_path(make, model, gen)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return path


def _read_candidate_cache(make, model, gen):
    """Rebuild (CandidateClaim, Document) pairs from the cache JSON."""
    from knowledge.extract import CandidateClaim
    from knowledge.sources.base import Document, Tier

    path = _cache_path(make, model, gen)
    if not path.exists():
        return None
    rows = json.loads(path.read_text())
    out = []
    for row in rows:
        claim = CandidateClaim(**row["claim"])
        d = row["doc"]
        doc = Document(
            text=d["text"],
            url=d["url"],
            tier=Tier(d["tier"]),
            site_or_channel=d["site_or_channel"],
            meta=d.get("meta", {}),
        )
        out.append((claim, doc))
    return out


def _find_data_file(subdir: str, make: str, model: str, gen: str) -> Path | None:
    """Find backend/data/{subdir}/{make}_{model}_{gen}.yaml (exact match on gen)."""
    exact = DATA_DIR / subdir / f"{make}_{model}_{gen}.yaml"
    if exact.exists():
        return exact
    # fallback: glob and warn if multiple found
    matches = sorted((DATA_DIR / subdir).glob(f"{make}_{model}*.yaml"))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        log.warning(
            "Multiple %s files for %s/%s — specify --gen. Using: %s",
            subdir, make, model, matches[0].name,
        )
        return matches[0]
    return None


def _build_variant_descriptors(variants_path: Path) -> list[tuple[str, str]]:
    """Return [(variant_id, human-readable description), ...] from variants YAML."""
    rows = yaml.safe_load(variants_path.read_text()) or []
    result = []
    for r in rows:
        desc = (
            f"{r.get('make','').title()} {r.get('model','').title()} "
            f"{r.get('generation','')} "
            f"{r.get('engine_code','')} "
            f"{r.get('fuel','')} "
            f"{r.get('displacement_cc','')}cc "
            f"{r.get('power_min_hp','')}–{r.get('power_max_hp','')}hp "
            f"({r.get('year_from','')}–{r.get('year_to') or 'present'})"
        ).strip()
        result.append((r["id"], desc))
    return result


def _build_variant_fuels(variants_path: Path) -> dict[str, str]:
    """Return {variant_id: fuel} so grounding can stay within a claim's fuel."""
    rows = yaml.safe_load(variants_path.read_text()) or []
    return {r["id"]: r.get("fuel") for r in rows if r.get("fuel")}


def _load_pending_entries(make: str, model: str, gen: str) -> list[dict]:
    path = CURATED_DIR / f"{make}_{model}_{gen}.yaml"
    if not path.exists():
        return []
    entries = yaml.safe_load(path.read_text()) or []
    return [e for e in entries if e.get("status", "pending") == "pending"]


def _mark_processed(make: str, model: str, gen: str, processed_ids: set[str]) -> None:
    """Update status=processed for the given video_ids/URLs in the curated YAML."""
    path = CURATED_DIR / f"{make}_{model}_{gen}.yaml"
    entries = yaml.safe_load(path.read_text()) or []
    today = str(date.today())
    for entry in entries:
        key = entry.get("video_id") or entry.get("url") or ""
        if key in processed_ids:
            entry["status"] = "processed"
            entry["processed_at"] = today
    path.write_text(yaml.dump(entries, allow_unicode=True, sort_keys=False))


def run(
    make: str,
    model: str,
    gen: str,
    dry_run: bool = False,
    skip_extraction: bool = False,
) -> None:
    from knowledge.extract import extract_claims
    from knowledge.promote import promote, write_promoted_claims
    from knowledge.sources.curated import CuratedSource

    # ── Resolve file paths ────────────────────────────────────────────────────
    variants_path = _find_data_file("variants", make, model, gen)
    if not variants_path:
        print(f"ERROR: No variants file found for {make}/{model}/{gen} in {DATA_DIR}/variants/")
        sys.exit(1)

    claims_dir = DATA_DIR / "claims"
    claims_path = _find_data_file("claims", make, model, gen)
    model_key = variants_path.stem[len(make) + 1:]   # "megane_4" from "renault_megane_4"

    # ── Build variant descriptors + fuel map for gate_variant ─────────────────
    variant_descriptors = _build_variant_descriptors(variants_path)
    variant_fuels = _build_variant_fuels(variants_path)

    all_candidates: list[tuple] = []
    processed_ids: set[str] = set()

    # ── Re-run path: load cached candidates, skip all fetch + extraction ───────
    if skip_extraction:
        all_candidates = _read_candidate_cache(make, model, gen) or []
        if not all_candidates:
            print(
                f"--skip-extraction: no cache at {_cache_path(make, model, gen)} "
                f"— run once without the flag first."
            )
            return
        print(
            f"--skip-extraction: loaded {len(all_candidates)} cached candidate(s) "
            f"(zero fetches, zero extraction calls).\n"
        )
    else:
        # ── Load pending entries ──────────────────────────────────────────────
        pending = _load_pending_entries(make, model, gen)
        if not pending:
            print(f"No pending sources for {make}/{model}.")
            return

        print(f"Processing {len(pending)} pending source(s) for {make}/{model}…\n")

        # ── Fetch + extract per source ────────────────────────────────────────
        source = CuratedSource()

        for i, entry in enumerate(pending, 1):
            entry_key = entry.get("video_id") or entry.get("url") or f"entry_{i}"
            entry_type = entry.get("type", "?")
            label = f"[{i}/{len(pending)}] {entry_type}:{entry_key[:40]}"

            print(f"{label} → fetching…", end="", flush=True)
            try:
                doc = source._fetch_entry(entry, make, model)
            except Exception as exc:
                print(f" FAILED ({exc})")
                continue

            if not doc:
                print(" no content (skipped)")
                continue

            print(f" {len(doc.text):,} chars", end="")

            try:
                claims = extract_claims(doc)
            except Exception as exc:
                print(f"\n  extract_claims failed: {exc}")
                continue

            print(f" → {len(claims)} claim(s) extracted")

            if dry_run:
                for c in claims:
                    print(f"      [{c.domain}/{c.severity}] {c.title[:60]}")
                processed_ids.add(entry_key)
                continue

            for c in claims:
                all_candidates.append((c, doc))
            processed_ids.add(entry_key)
            # Mark immediately so reruns skip already-extracted sources
            _mark_processed(make, model, gen, {entry_key})

        if dry_run:
            print(f"\nDRY RUN — no changes written. Would process {len(processed_ids)} source(s).")
            return

        if not all_candidates:
            print("\nNo claims extracted. Marking sources processed.")
            _mark_processed(make, model, gen, processed_ids)
            return

        # Cache candidates so a later --skip-extraction re-run is free.
        cache_path = _write_candidate_cache(make, model, gen, all_candidates)
        print(f"Cached {len(all_candidates)} candidate(s) → {cache_path}\n")

    # ── Promote (dedup + gate + score handled internally) ────────────────────
    print(f"Promoting {len(all_candidates)} candidate claim(s) (dedup + gates + score)…")
    results = promote(
        all_candidates, variant_descriptors,
        claim_key_prefix=f"{make}_{model_key}", variant_fuels=variant_fuels,
    )

    # ── Print results ─────────────────────────────────────────────────────────
    counts = {d: 0 for d in ["verified", "review", "held", "rejected"]}
    for r in results:
        counts[r.disposition.value] += 1
        icon = {"verified": "✓", "review": "⚠", "held": "·", "rejected": "✗"}.get(r.disposition.value, "?")
        print(f"  {icon} [{r.claim.domain}/{r.claim.severity}] {r.claim.title[:55]}")
        print(f"      score={r.score:.2f} → {r.disposition.value} ({r.reason})")

    # ── Write to claims YAML ──────────────────────────────────────────────────
    write_promoted_claims(results, make, model_key, claims_dir)
    print(
        f"\nSummary: {len(results)} claims — "
        f"{counts['verified']} auto-verified, "
        f"{counts['review']} review, "
        f"{counts['held']} held, "
        f"{counts['rejected']} rejected"
    )
    print(f"Claims YAML: {claims_path or claims_dir / f'{make}_{model_key}.yaml'}")

    print(f"Sources processed: {len(processed_ids)} marked during extraction")

    # ── Sync to DB ────────────────────────────────────────────────────────────
    print("\nSyncing to DB…", end="", flush=True)
    try:
        import os
        os.chdir(REPO_ROOT)
        from backend.sync import run as sync_run
        sync_run()
        print(" OK")
    except Exception as exc:
        print(f" FAILED ({exc})")
        print("Run manually: docker compose -f deploy/docker-compose.yml restart api")


def _load_all_variants_for_part(part_id: str, part_type: str) -> list[tuple[str, str]]:
    """Return [(variant_id, description)] for all variants that use this part.

    Reads all fitment YAMLs and resolves variant descriptors for gate_variant.
    Part type determines which fitment field to match:
      engine       → engine_family
      transmission → transmission_code
    """
    fitment_dir = DATA_DIR / "fitment"
    variants_dir = DATA_DIR / "variants"
    field = "engine_family" if part_type == "engine" else "transmission_code"

    matching_variant_ids: list[str] = []
    for path in sorted(fitment_dir.glob("*.yaml")):
        rows = yaml.safe_load(path.read_text()) or []
        for row in rows:
            if row.get(field) == part_id:
                matching_variant_ids.append(row["variant_id"])

    if not matching_variant_ids:
        return []

    # Load descriptors from variants YAMLs
    all_variants: dict[str, dict] = {}
    for path in sorted(variants_dir.glob("*.yaml")):
        for row in (yaml.safe_load(path.read_text()) or []):
            all_variants[row["id"]] = row

    result = []
    for vid in matching_variant_ids:
        if vid not in all_variants:
            continue
        r = all_variants[vid]
        desc = (
            f"{r.get('make','').title()} {r.get('model','').title()} "
            f"{r.get('generation','')} "
            f"{r.get('engine_code','')} "
            f"{r.get('fuel','')} "
            f"{r.get('displacement_cc','')}cc "
            f"{r.get('power_min_hp','')}–{r.get('power_max_hp','')}hp "
            f"({r.get('year_from','')}–{r.get('year_to') or 'present'})"
        ).strip()
        result.append((vid, desc))
    return result


def run_part(
    part_id: str,
    part_type: str,
    dry_run: bool = False,
    skip_extraction: bool = False,
) -> None:
    """Run the knowledge pipeline for a specific part revision.

    Sources are read from curated/part_{part_id}_{part_type}.yaml.
    Claims are written to backend/data/parts/{part_type}/{part_id}.yaml.
    Variant descriptors for gate_variant come from all variants with matching fitment.
    """
    from knowledge.extract import extract_claims
    from knowledge.promote import promote, write_promoted_part_claims
    from knowledge.sources.curated import CuratedSource

    # part_id doubles as "model" slug in curated YAML naming
    slug_make  = "part"
    slug_model = part_id
    slug_gen   = part_type

    variant_descriptors = _load_all_variants_for_part(part_id, part_type)
    if not variant_descriptors:
        print(
            f"WARNING: No variants found for {part_type} part {part_id!r} in any fitment YAML. "
            f"gate_variant will have nothing to ground against — claims will be HELD."
        )
        variant_descriptors = []

    variant_fuels: dict[str, str] = {}
    for vid, _ in variant_descriptors:
        # Load fuel from all variant YAMLs
        for path in sorted((DATA_DIR / "variants").glob("*.yaml")):
            for row in (yaml.safe_load(path.read_text()) or []):
                if row["id"] == vid:
                    variant_fuels[vid] = row.get("fuel", "")

    all_candidates: list[tuple] = []
    processed_ids: set[str] = set()

    if skip_extraction:
        all_candidates = _read_candidate_cache(slug_make, slug_model, slug_gen) or []
        if not all_candidates:
            print(
                f"--skip-extraction: no cache at {_cache_path(slug_make, slug_model, slug_gen)} "
                f"— run once without the flag first."
            )
            return
        print(f"--skip-extraction: loaded {len(all_candidates)} cached candidate(s)\n")
    else:
        pending = _load_pending_entries(slug_make, slug_model, slug_gen)
        if not pending:
            print(f"No pending sources for part {part_id!r} — add sources to curated/part_{part_id}_{part_type}.yaml")
            return

        print(f"Processing {len(pending)} pending source(s) for part {part_id!r}…\n")
        source = CuratedSource()

        for i, entry in enumerate(pending, 1):
            entry_key = entry.get("video_id") or entry.get("url") or f"entry_{i}"
            label = f"[{i}/{len(pending)}] {entry.get('type','?')}:{entry_key[:40]}"
            print(f"{label} → fetching…", end="", flush=True)
            try:
                doc = source._fetch_entry(entry, slug_make, slug_model)
            except Exception as exc:
                print(f" FAILED ({exc})")
                continue
            if not doc:
                print(" no content (skipped)")
                continue
            print(f" {len(doc.text):,} chars", end="")
            try:
                claims = extract_claims(doc)
            except Exception as exc:
                print(f"\n  extract_claims failed: {exc}")
                continue
            print(f" → {len(claims)} claim(s) extracted")
            if dry_run:
                for c in claims:
                    print(f"      [{c.domain}/{c.severity}] {c.title[:60]}")
                processed_ids.add(entry_key)
                continue
            for c in claims:
                all_candidates.append((c, doc))
            processed_ids.add(entry_key)
            _mark_processed(slug_make, slug_model, slug_gen, {entry_key})

        if dry_run:
            print(f"\nDRY RUN — no changes written.")
            return
        if not all_candidates:
            print("\nNo claims extracted.")
            return
        cache_path = _write_candidate_cache(slug_make, slug_model, slug_gen, all_candidates)
        print(f"Cached {len(all_candidates)} candidate(s) → {cache_path}\n")

    print(f"Promoting {len(all_candidates)} candidate claim(s)…")
    results = promote(
        all_candidates, variant_descriptors,
        claim_key_prefix=part_id, variant_fuels=variant_fuels,
    )

    counts = {d: 0 for d in ["verified", "review", "held", "rejected"]}
    for r in results:
        counts[r.disposition.value] += 1
        icon = {"verified": "✓", "review": "⚠", "held": "·", "rejected": "✗"}.get(r.disposition.value, "?")
        print(f"  {icon} [{r.claim.domain}/{r.claim.severity}] {r.claim.title[:55]}")
        print(f"      score={r.score:.2f} → {r.disposition.value} ({r.reason})")

    write_promoted_part_claims(results, part_id, part_type, DATA_DIR / "parts")
    print(
        f"\nSummary: {len(results)} claims — "
        f"{counts['verified']} auto-verified, "
        f"{counts['review']} review, "
        f"{counts['held']} held, "
        f"{counts['rejected']} rejected"
    )
    print(f"Part claims: backend/data/parts/{part_type}/{part_id}.yaml")

    print("\nSyncing to DB…", end="", flush=True)
    try:
        import os
        os.chdir(REPO_ROOT)
        from backend.sync import run as sync_run
        sync_run()
        print(" OK")
    except Exception as exc:
        print(f" FAILED ({exc})")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Process pending curated sources through the knowledge pipeline."
    )
    parser.add_argument("make",  nargs="?", help="Car make (model-centric mode)")
    parser.add_argument("model", nargs="?", help="Car model (model-centric mode)")
    parser.add_argument("gen",   nargs="?", help="Generation key (model-centric mode)")
    parser.add_argument("--part", metavar="PART_ID",
                        help="Part ID for part-centric mode (e.g. k9k, edc, ea211)")
    parser.add_argument("--part-type", choices=["engine", "transmission"],
                        help="Part type (required with --part)")
    parser.add_argument("--dry-run", action="store_true", help="Print what would run, no writes")
    parser.add_argument(
        "--skip-extraction",
        action="store_true",
        help="Re-run gates + promotion on cached candidates (no fetch, no extraction LLM calls)",
    )
    args = parser.parse_args()

    if args.part:
        if not args.part_type:
            parser.error("--part requires --part-type")
        run_part(
            args.part.lower(),
            args.part_type,
            dry_run=args.dry_run,
            skip_extraction=args.skip_extraction,
        )
    else:
        if not (args.make and args.model and args.gen):
            parser.error("model-centric mode requires make, model, and gen positional arguments")
        run(
            args.make.lower(),
            args.model.lower(),
            args.gen.lower(),
            dry_run=args.dry_run,
            skip_extraction=args.skip_extraction,
        )


if __name__ == "__main__":
    main()
