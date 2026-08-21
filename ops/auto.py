"""auto.py — fully automated knowledge acquisition pipeline.

Generates search queries from the variants YAML, discovers web pages via Exa
and YouTube videos via yt-dlp, writes them to curated YAML, then runs the
full extraction + promotion pipeline.

Usage:
    python -m ops.auto renault megane 4
    python -m ops.auto toyota corolla e210 --dry-run
    python -m ops.auto renault megane 4 --no-youtube
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import yaml
from dotenv import load_dotenv

from knowledge.parts.search_templates import ensure_part_stub
from knowledge.stoplists import FORUM_DOMAINS

# load dotenv
load_dotenv()

log = logging.getLogger(__name__)

CURATED_DIR = Path(__file__).parent / "sources" / "curated"

# ── Dedup helpers ─────────────────────────────────────────────────────────────


def _load_known_urls() -> set[str]:
    urls: set[str] = set()
    if not CURATED_DIR.exists():
        return urls
    for p in CURATED_DIR.glob("*.yaml"):
        for e in yaml.safe_load(p.read_text()) or []:
            if e.get("url"):
                urls.add(e["url"])
    return urls


def _load_known_video_ids() -> set[str]:
    ids: set[str] = set()
    if not CURATED_DIR.exists():
        return ids
    for p in CURATED_DIR.glob("*.yaml"):
        for e in yaml.safe_load(p.read_text()) or []:
            if e.get("video_id"):
                ids.add(e["video_id"])
    return ids


# ── Exa web discovery ─────────────────────────────────────────────────────────


_EXCLUDE_DOMAINS = [
    # Marketplaces and classified-listing noise
    "pinterest.com", "ebay.com", "ebay.co.uk", "ebay.de", "ebay.fr",
    "sahibinden.com", "arabam.com", "otomoto.pl", "mobile.de",
    "autotrader.co.uk", "gumtree.com",
    # Forums, owner clubs, and complaint boards — one-time/anecdotal issues
    # read like chronic patterns once extracted. See knowledge/stoplists.py.
    *FORUM_DOMAINS,
]


def _exa_search(
    exa,
    query: str,
    known_urls: set[str],
    num_results: int,
    include_domains: list[str] | None = None,
) -> list[dict]:
    """Run one Exa query and return new (not-yet-seen) page dicts."""
    kwargs = {"num_results": num_results, "type": "auto", "exclude_domains": _EXCLUDE_DOMAINS}
    if include_domains:
        kwargs["include_domains"] = include_domains
    try:
        resp = exa.search(query, **kwargs)
    except Exception as exc:
        log.warning("Exa search failed for %r: %s", query, exc)
        return []

    found = []
    for r in resp.results:
        url = r.url
        if url in known_urls:
            continue
        host = urlparse(url).netloc.lower().removeprefix("www.")
        found.append({"url": url, "site_or_channel": host,
                      "notes": (getattr(r, "title", "") or query)[:80]})
        known_urls.add(url)
    return found


def _discover_web(
    templates: list[tuple[str, str]],
    known_urls: set[str],
    max_per_query: int = 5,
) -> list[dict]:
    try:
        from exa_py import Exa
    except ImportError:
        print("  exa-py not installed — skipping web search  (pip install exa-py)")
        return []

    api_key = os.getenv("EXA_API_KEY")
    if not api_key:
        print("  EXA_API_KEY not set — skipping web search")
        return []

    exa = Exa(api_key=api_key)
    found: list[dict] = []

    for _, query in templates:
        found.extend(_exa_search(exa, query, known_urls, num_results=max_per_query))

    return found


# ── YouTube discovery ─────────────────────────────────────────────────────────


def _discover_youtube(
    templates: list[tuple[str, str]],
    known_ids: set[str],
    max_per_query: int = 8,
) -> list[dict]:
    try:
        import yt_dlp
    except ImportError:
        print("  yt-dlp not installed — skipping YouTube search")
        return []

    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "playlist_items": f"1-{max_per_query}",
    }
    found: list[dict] = []

    for _, query in templates:
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(
                    f"ytsearch{max_per_query}:{query}", download=False
                )
                videos = [v for v in (info.get("entries") or []) if v and v.get("id")]
        except Exception as exc:
            log.warning("yt-dlp search failed for %r: %s", query, exc)
            continue

        for v in videos:
            vid_id = v["id"]
            if vid_id in known_ids:
                continue
            found.append(v)
            known_ids.add(vid_id)

    return found


# ── Cap selection — pages first, then YouTube ─────────────────────────────────


def _select_capped(
    pages: list[dict],
    videos: list[dict],
    cap: int,
) -> tuple[list[dict], list[dict]]:
    """Keep at most `cap` sources, ranked by chronic-signal score.

    Backported from knowledge/ledger/acquire.py's rank_sources (backlog B8):
    score by part-code specificity in the title + failure-signal vocabulary,
    pages first, then YouTube filling remaining budget. This replaces the old
    discovery-order selection so the ≤cap extracted sources are the ones most
    likely to describe chronics, not the first N Exa returned.
    """
    _TITLE_FAILURE_STEMS = (
        "problem", "arıza", "ariza", "sorun", "kronik", "fail", "fault", "recall",
        "issue", "broken", "repair", "worn", "wear", "leak", "defect", "chronic",
    )

    def _score(item: dict) -> int:
        title = (item.get("title") or item.get("notes") or "").lower()
        score = sum(1 for stem in _TITLE_FAILURE_STEMS if stem in title)
        # Penalize forum domains (still allowed, but ranked below editorial)
        from knowledge.stoplists import FORUM_DOMAINS
        site = (item.get("site_or_channel") or "").lower()
        if any(fd in site for fd in FORUM_DOMAINS):
            score -= 1
        return score

    pages.sort(key=_score, reverse=True)
    videos.sort(key=_score, reverse=True)

    kept_pages = pages[:cap]
    remaining = cap - len(kept_pages)
    kept_videos = videos[:remaining] if remaining > 0 else []
    return kept_pages, kept_videos


# ── Write discovered sources to curated YAML (one atomic write) ───────────────


def _write_discovered(
    pages: list[dict],
    videos: list[dict],
    make: str,
    model: str,
    gen: str,
) -> None:
    CURATED_DIR.mkdir(parents=True, exist_ok=True)
    path = CURATED_DIR / f"{make}_{model}_{gen}.yaml"
    existing = (yaml.safe_load(path.read_text()) or []) if path.exists() else []
    today = str(date.today())

    for p in pages:
        existing.append(
            {
                "type": "page",
                "url": p["url"],
                "site_or_channel": p["site_or_channel"],
                "notes": p["notes"],
                "status": "pending",
                "added_at": today,
                "processed_at": None,
            }
        )

    for v in videos:
        existing.append(
            {
                "type": "youtube",
                "video_id": v["id"],
                "site_or_channel": (v.get("channel") or v.get("uploader") or "YouTube")[
                    :60
                ],
                "notes": (v.get("title") or "")[:80],
                "status": "pending",
                "added_at": today,
                "processed_at": None,
            }
        )

    path.write_text(yaml.dump(existing, allow_unicode=True, sort_keys=False))


# ── Orchestrator — model-centric mode ────────────────────────────────────────


def run(
    make: str,
    model: str,
    gen: str,
    dry_run: bool = False,
    web: bool = True,
    youtube: bool = True,
    max_web: int = 5,
    max_yt: int = 3,
    max_sources: int = 25,
) -> None:
    from knowledge.discover import _generate_templates
    from ops.process import run as process_run

    templates = _generate_templates(make, model, gen)
    if not templates:
        print(
            f"No templates generated — does backend/data/variants/{make}_{model}_{gen}.yaml exist?"
        )
        sys.exit(1)

    domains = {d for d, _ in templates}
    print(
        f"Generated {len(templates)} search queries across {len(domains)} domains: {', '.join(sorted(domains))}\n"
    )

    # ── Web ───────────────────────────────────────────────────────────────────
    pages: list[dict] = []
    if web:
        known_urls = _load_known_urls()
        print(f"Searching web (Exa) — {max_web} results per query…")
        pages = _discover_web(templates, known_urls, max_per_query=max_web)
        if pages:
            for p in pages:
                print(f"  {p['url'][:75]}")
        print(f"  → {len(pages)} new page(s)\n")

    # ── YouTube ───────────────────────────────────────────────────────────────
    videos: list[dict] = []
    if youtube:
        known_ids = _load_known_video_ids()
        print(f"Searching YouTube (yt-dlp) — {max_yt} results per query…")
        videos = _discover_youtube(templates, known_ids, max_per_query=max_yt)
        print(f"  → {len(videos)} new video(s)\n")

    if not pages and not videos:
        print(
            "Nothing new discovered — all sources already in curated YAML or not allowlisted."
        )
        return

    # ── Cap — pages first, then YouTube ───────────────────────────────────────
    total_found = len(pages) + len(videos)
    pages, videos = _select_capped(pages, videos, max_sources)
    kept = len(pages) + len(videos)
    if kept < total_found:
        print(
            f"Capped {total_found} → {kept} source(s) "
            f"(max-sources={max_sources}; dropped {total_found - kept} YouTube)\n"
        )

    if dry_run:
        print(
            f"DRY RUN — would add {len(pages)} page(s) and {len(videos)} video(s). No writes."
        )
        return

    # ── Write + process ───────────────────────────────────────────────────────
    _write_discovered(pages, videos, make, model, gen)
    print(
        f"Wrote {len(pages)} page(s) + {len(videos)} video(s) to curated/{make}_{model}_{gen}.yaml"
    )
    print(f"\nRunning pipeline…\n{'─' * 60}")
    process_run(make, model, gen)


# ── Orchestrator — part-centric mode ─────────────────────────────────────────


def run_part(
    part_id: str,
    part_type: str,
    fuel: str = "",
    dry_run: bool = False,
    web: bool = True,
    youtube: bool = True,
    max_web: int = 5,
    max_yt: int = 3,
    max_sources: int = 25,
) -> None:
    """Discover sources for a specific part revision (e.g. k9k engine, edc transmission).

    Uses part-centric search queries ("{part_id} engine problems") rather than
    model-centric ones. Sources are written to knowledge/sources/curated/part_{part_id}.yaml
    and then processed through the standard extraction + promotion pipeline.
    """
    from knowledge.parts.search_templates import _find_make_model_for_part, templates_for_part
    from ops.process import run_part as process_run_part

    # Ensure a scaffold stub exists before writing any claims — mirrors what
    # run_all_parts does per part. Without this, write_promoted_part_claims
    # (promote.py) writes a bare {"claims": [...]} for a genuinely new part,
    # missing part_id/part_type/display_name/manufacturer entirely (only ever
    # unnoticed before because every prior --part invocation targeted a part
    # --all-parts had already scaffolded).
    make, model = _find_make_model_for_part(part_id, part_type)
    if make and model:
        variants_path = VARIANTS_DIR / f"{make}_{model}.yaml"
        if variants_path.exists():
            variants = yaml.safe_load(variants_path.read_text()) or []
            _ensure_part_stub(part_id, part_type, make, model, variants, dry_run=dry_run)

    hints = {"fuel": fuel} if fuel else {}
    templates = templates_for_part(part_id, part_type, hints)
    if not templates:
        print(f"No templates generated for part {part_id!r}")
        sys.exit(1)

    domains = {d for d, _ in templates}
    print(
        f"Part-centric: {len(templates)} queries for {part_id!r} across "
        f"{len(domains)} domains: {', '.join(sorted(domains))}\n"
    )

    # Use part_{part_id} as the slug for curated YAML so it doesn't collide with
    # model-centric curated files.
    slug_make  = "part"
    slug_model = part_id
    slug_gen   = part_type

    pages: list[dict] = []
    if web:
        known_urls = _load_known_urls()
        print(f"Searching web (Exa) — {max_web} results per query…")
        pages = _discover_web(templates, known_urls, max_per_query=max_web)
        if pages:
            for p in pages:
                print(f"  {p['url'][:75]}")
        print(f"  → {len(pages)} new page(s)\n")

    videos: list[dict] = []
    if youtube:
        known_ids = _load_known_video_ids()
        print(f"Searching YouTube (yt-dlp) — {max_yt} results per query…")
        videos = _discover_youtube(templates, known_ids, max_per_query=max_yt)
        print(f"  → {len(videos)} new video(s)\n")

    if not pages and not videos:
        print("Nothing new discovered.")
        return

    total_found = len(pages) + len(videos)
    pages, videos = _select_capped(pages, videos, max_sources)
    kept = len(pages) + len(videos)
    if kept < total_found:
        print(f"Capped {total_found} → {kept} source(s)\n")

    if dry_run:
        print(f"DRY RUN — would add {len(pages)} page(s) and {len(videos)} video(s). No writes.")
        return

    _write_discovered(pages, videos, slug_make, slug_model, slug_gen)
    print(f"Wrote {len(pages)} page(s) + {len(videos)} video(s) to curated/part_{part_id}_{part_type}.yaml")
    print(f"\nRunning pipeline…\n{'─' * 60}")
    process_run_part(part_id, part_type)


# ── Orchestrator — all-parts mode ────────────────────────────────────────────

REPO_ROOT = Path(__file__).parent.parent
VARIANTS_DIR = REPO_ROOT / "backend" / "data" / "variants"
PARTS_DIR = REPO_ROOT / "backend" / "data" / "parts"


def _infer_part_type(part_id: str) -> str | None:
    """Return 'engine'|'transmission'|'cooling'|'electrical'|'body' by scanning parts dir."""
    for subdir in ("engine", "transmission", "cooling", "electrical", "body"):
        if (PARTS_DIR / subdir / f"{part_id}.yaml").exists():
            return subdir
    return None


def _ensure_part_stub(
    part_id: str,
    part_type: str,
    make: str,
    model: str,
    variants: list[dict],
    *,
    dry_run: bool = False,
) -> None:
    ensure_part_stub(part_id, part_type, make, model, variants, dry_run=dry_run)


def run_all_parts(
    make: str,
    model: str,
    **kwargs,
) -> None:
    """Discover all engine families and transmission codes from the variants YAML
    and run the pipeline for each part sequentially.

    Usage:
        python -m ops.auto --make volkswagen --model golf_7 --all-parts
    """
    variants_path = VARIANTS_DIR / f"{make}_{model}.yaml"
    if not variants_path.exists():
        print(f"Variants YAML not found: {variants_path}")
        sys.exit(1)

    variants: list[dict] = yaml.safe_load(variants_path.read_text()) or []

    # Collect unique parts per type from variants YAML
    engines: dict[str, str] = {}   # engine_family → fuel
    transmissions: set[str] = set()
    cooling_codes: set[str] = set()
    electrical_codes: set[str] = set()
    body_codes: set[str] = set()

    for v in variants:
        ef = (v.get("engine_family") or "").strip()
        if ef and ef != "manual":
            fuel = (v.get("fuel") or "").lower()
            engines.setdefault(ef, fuel)

        for code, bucket in (
            ("transmission_code", transmissions),
            ("cooling_code", cooling_codes),
            ("electrical_code", electrical_codes),
            ("body_code", body_codes),
        ):
            val = (v.get(code) or "").strip()
            if val and val != "manual":
                bucket.add(val)

    total = len(engines) + len(transmissions) + len(cooling_codes) + len(electrical_codes) + len(body_codes)
    print(f"\nModel: {make} {model}")
    print(f"Parts to process: {len(engines)} engine(s) + {len(transmissions)} transmission(s)"
          f" + {len(cooling_codes)} cooling + {len(electrical_codes)} electrical + {len(body_codes)} body\n")
    for ef, fuel in sorted(engines.items()):
        print(f"  engine      : {ef}" + (f" ({fuel})" if fuel else ""))
    for tc in sorted(transmissions):
        print(f"  transmission: {tc}")
    for cc in sorted(cooling_codes):
        print(f"  cooling     : {cc}")
    for ec in sorted(electrical_codes):
        print(f"  electrical  : {ec}")
    for bc in sorted(body_codes):
        print(f"  body        : {bc}")
    print()

    dry_run = kwargs.get("dry_run", False)
    done = 0
    for ef, fuel in sorted(engines.items()):
        done += 1
        print(f"\n{'═' * 60}")
        print(f"[{done}/{total}] ENGINE: {ef}  fuel={fuel or '?'}")
        print(f"{'═' * 60}\n")
        _ensure_part_stub(ef, "engine", make, model, variants, dry_run=dry_run)
        run_part(ef, "engine", fuel=fuel, **kwargs)

    for tc in sorted(transmissions):
        done += 1
        print(f"\n{'═' * 60}")
        print(f"[{done}/{total}] TRANSMISSION: {tc}")
        print(f"{'═' * 60}\n")
        _ensure_part_stub(tc, "transmission", make, model, variants, dry_run=dry_run)
        run_part(tc, "transmission", **kwargs)

    for cc in sorted(cooling_codes):
        done += 1
        print(f"\n{'═' * 60}")
        print(f"[{done}/{total}] COOLING: {cc}")
        print(f"{'═' * 60}\n")
        _ensure_part_stub(cc, "cooling", make, model, variants, dry_run=dry_run)
        run_part(cc, "cooling", **kwargs)

    for ec in sorted(electrical_codes):
        done += 1
        print(f"\n{'═' * 60}")
        print(f"[{done}/{total}] ELECTRICAL: {ec}")
        print(f"{'═' * 60}\n")
        _ensure_part_stub(ec, "electrical", make, model, variants, dry_run=dry_run)
        run_part(ec, "electrical", **kwargs)

    for bc in sorted(body_codes):
        done += 1
        print(f"\n{'═' * 60}")
        print(f"[{done}/{total}] BODY: {bc}")
        print(f"{'═' * 60}\n")
        _ensure_part_stub(bc, "body", make, model, variants, dry_run=dry_run)
        run_part(bc, "body", **kwargs)

    print(f"\n{'═' * 60}")
    print(f"All {total} part pipeline(s) complete for {make} {model}.")
    print(f"{'═' * 60}")


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(
        description="Auto-discover sources and run the full knowledge pipeline."
    )
    # Model-centric positional args (old mode, kept for backward compat)
    parser.add_argument("make_pos", nargs="?", metavar="make",
                        help="Car make (model-centric mode, positional)")
    parser.add_argument("model_pos", nargs="?", metavar="model",
                        help="Car model (model-centric mode, positional)")
    parser.add_argument("gen_pos", nargs="?", metavar="gen",
                        help="Generation key (model-centric mode, positional)")
    # Named make/model (used with --all-parts and --part)
    parser.add_argument("--make", help="Car make (e.g. volkswagen, renault)")
    parser.add_argument("--model", help="Model key matching variants YAML (e.g. golf_7)")
    # All-parts mode
    parser.add_argument("--all-parts", action="store_true",
                        help="Run pipeline for every engine family and transmission in the variants YAML")
    # Part-centric mode
    parser.add_argument("--part", metavar="PART_ID",
                        help="Part ID (e.g. k9k, edc, ea211, dq200)")
    parser.add_argument("--part-type", choices=["engine", "transmission", "cooling", "electrical", "body"],
                        help="Part type (required with --part unless auto-detected)")
    parser.add_argument("--fuel", default="",
                        choices=["", "diesel", "petrol"],
                        help="Fuel type hint for part-specific queries")
    # Shared flags
    parser.add_argument("--dry-run", action="store_true",
                        help="Discover only — print what would be added, no writes")
    parser.add_argument("--no-web", action="store_true", help="Skip Exa web search")
    parser.add_argument("--no-youtube", action="store_true", help="Skip YouTube search")
    parser.add_argument("--max-web", type=int, default=5)
    parser.add_argument("--max-yt", type=int, default=3)
    parser.add_argument("--max-sources", type=int, default=15)
    args = parser.parse_args()

    shared = dict(
        dry_run=args.dry_run,
        web=not args.no_web,
        youtube=not args.no_youtube,
        max_web=args.max_web,
        max_yt=args.max_yt,
        max_sources=args.max_sources,
    )

    if args.all_parts:
        make = (args.make or args.make_pos or "").lower()
        model = (args.model or args.model_pos or "").lower()
        if not make or not model:
            parser.error("--all-parts requires --make and --model")
        run_all_parts(make, model, **shared)

    elif args.part:
        part_id = args.part.lower()
        part_type = args.part_type
        if not part_type:
            part_type = _infer_part_type(part_id)
            if not part_type:
                parser.error(f"--part-type not given and no part YAML found for {part_id!r}")
            print(f"Auto-detected part type: {part_type}")
        run_part(part_id, part_type, fuel=args.fuel, **shared)

    else:
        # Legacy positional model-centric mode
        make = (args.make or args.make_pos or "").lower()
        model = (args.model or args.model_pos or "").lower()
        gen = args.gen_pos or ""
        if not (make and model and gen):
            parser.error("model-centric mode requires make, model, and gen (positional or --make/--model/--gen)")
        run(make, model, gen.lower(), **shared)


if __name__ == "__main__":
    main()
