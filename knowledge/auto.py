"""auto.py — fully automated knowledge acquisition pipeline.

Generates search queries from the variants YAML, discovers web pages via Exa
and YouTube videos via yt-dlp, writes them to curated YAML, then runs the
full extraction + promotion pipeline.

Usage:
    python -m knowledge.auto renault megane 4
    python -m knowledge.auto toyota corolla e210 --dry-run
    python -m knowledge.auto renault megane 4 --no-youtube
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

# load dotenv
load_dotenv()

log = logging.getLogger(__name__)

CURATED_DIR = Path(__file__).parent / "sources" / "curated"

# ── Tier assignment ───────────────────────────────────────────────────────────
# Known specialist domains → Tier A (weight 1.0).
# Forum/community heuristics → Tier B (weight 0.5).
# Everything else → Tier C (weight 0.34, high-recall/high-noise).
# Two unknowns: 0.34+0.34=0.68 → HELD. Three: 1.02 → barely promotes.
# A+C: 1.34 → promotes (safe, A is human-vetted). B alone: 0.5 → HELD.

TIER_A_DOMAINS: set[str] = {
    "enginefinders.co.uk",
    "balancemotorworks.co.uk",
    "autoricambitritella.it",
    "gaga.ba",
    "fiches-auto.fr",
    "asrgearboxrepairs.co.uk",  # UK specialist gearbox repair — EDC / dual-clutch
    "eco-torque.co.uk",         # UK specialist gearbox — Renault EDC DC4/DW5/DW6
    "enginecode.uk",            # K9K / H5F / H5H engine reliability reports
}

# Owner clubs, established reliability/review sites, and high-signal Turkish forums.
# A single Tier B source (weight 0.5) is sufficient for auto-verification of
# non-high-severity claims; two Tier B sources always auto-verify.
TIER_B_DOMAINS: set[str] = {
    # English owner clubs and reliability media
    "meganeownersclub.co.uk",
    "renaultownersclub.co.uk",
    "capturownersclub.co.uk",
    "honestjohn.co.uk",
    "pistonheads.com",
    "whatcar.com",
    "carbuyer.co.uk",
    "autoexpress.co.uk",
    "parkers.co.uk",
    "vehiclewise.co.uk",
    "daciaforum.co.uk",
    # Turkish high-signal communities (complaint volume = signal)
    "donanimhaber.com",
    "sikayetvar.com",
    "arabam.com.tr",
    "arabakolik.net",
    "kronikuzman.com",
    "kroniksorunlar.net",
}

# Domains to target with include_domains searches for high-value reliability content.
# Queried directly with Exa to guarantee at least some high-tier results per run.
_SPECIALIST_TARGET_DOMAINS: list[str] = [
    "meganeownersclub.co.uk",
    "honestjohn.co.uk",
    "pistonheads.com",
    "donanimhaber.com",
    "whatcar.com",
    "carbuyer.co.uk",
]

_FORUM_SIGNALS = {"forum", "forums", "community", "club", "owners", "subreddit"}


def _tier_for_url(url: str) -> str:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    if host in TIER_A_DOMAINS:
        return "A"
    if host in TIER_B_DOMAINS:
        return "B"
    if "reddit.com" in host or any(s in host for s in _FORUM_SIGNALS):
        return "B"
    return "C"  # unknown domain — Tier C (high-recall/high-noise), needs 3× or A+C to promote


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
    # JS-challenge / login-gated forums — fetchable only with a full browser;
    # trafilatura returns ~57 chars (JS challenge payload), no actual content.
    "renaultforums.co.uk",
    "frenchcarforum.co.uk",
    "daciaforum.co.uk",
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
        tier = _tier_for_url(url)
        host = urlparse(url).netloc.lower().removeprefix("www.")
        found.append({"url": url, "tier": tier, "site_or_channel": host,
                      "notes": (getattr(r, "title", "") or query)[:80]})
        known_urls.add(url)
    return found


def _discover_web(
    templates: list[tuple[str, str]],
    known_urls: set[str],
    make: str,
    model: str,
    gen_label: str,
    max_per_query: int = 5,
    specialist_domains: list[str] | None = None,
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

    # ── Broad template queries ────────────────────────────────────────────────
    for _, query in templates:
        found.extend(_exa_search(exa, query, known_urls, num_results=max_per_query))

    # ── Specialist domain pass — guarantee ≥1 Tier B hit per key domain ───────
    # Each target domain gets a focused reliability query so we always pull from
    # owner clubs / established review sites rather than relying on Tier C pages.
    # In part-centric mode, pass only part-relevant forums (owner clubs, Turkish
    # forums) — generic car review sites (whatcar, carbuyer) return other-car content.
    if specialist_domains is None:
        specialist_domains = _SPECIALIST_TARGET_DOMAINS
    reliability_query = f"{make.title()} {model.title()} {gen_label} problems reliability known issues"
    for domain in specialist_domains:
        results = _exa_search(exa, reliability_query, known_urls,
                              num_results=3, include_domains=[domain])
        if results:
            print(f"  [specialist:{domain[:30]}] {len(results)} result(s)")
        found.extend(results)

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


# ── Cap selection — prioritise Tier A/B, trim Tier C YouTube first ────────────


def _select_capped(
    pages: list[dict],
    videos: list[dict],
    cap: int,
) -> tuple[list[dict], list[dict]]:
    """Keep at most `cap` sources, ordered by trust: Tier A pages, then Tier B
    pages, then Tier C pages, then YouTube (all Tier C, highest-noise → trimmed
    first). Search is cheap; LLM extraction is not, so we cap what we extract.
    """
    tier_rank = {"A": 0, "B": 1, "C": 2}
    ordered_pages = sorted(pages, key=lambda p: tier_rank.get(p["tier"], 3))

    kept_pages = ordered_pages[:cap]
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
                "tier": p["tier"],
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
                "tier": "C",
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
    max_web: int = 3,
    max_yt: int = 3,
    max_sources: int = 25,
) -> None:
    from knowledge.discover import _generate_templates
    from knowledge.process import run as process_run

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

    # Derive the human-readable generation label used in specialist searches.
    try:
        import yaml as _yaml
        from pathlib import Path as _Path
        _vpath = _Path(__file__).parent.parent / "backend" / "data" / "variants" / f"{make}_{model}_{gen}.yaml"
        _rows = _yaml.safe_load(_vpath.read_text()) if _vpath.exists() else []
        gen_label = (_rows[0].get("generation", gen) if _rows else gen)
    except Exception:
        gen_label = gen

    # ── Web ───────────────────────────────────────────────────────────────────
    pages: list[dict] = []
    if web:
        known_urls = _load_known_urls()
        print(f"Searching web (Exa) — {max_web} results per query + specialist domain pass…")
        pages = _discover_web(templates, known_urls, make=make, model=model,
                              gen_label=gen_label, max_per_query=max_web)
        if pages:
            for p in pages:
                print(f"  [{p['tier']}] {p['url'][:75]}")
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

    # ── Cap — prioritise Tier A/B, trim Tier C YouTube first ──────────────────
    total_found = len(pages) + len(videos)
    pages, videos = _select_capped(pages, videos, max_sources)
    kept = len(pages) + len(videos)
    if kept < total_found:
        print(
            f"Capped {total_found} → {kept} source(s) "
            f"(max-sources={max_sources}; dropped {total_found - kept}, Tier C first)\n"
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
    max_web: int = 3,
    max_yt: int = 3,
    max_sources: int = 25,
) -> None:
    """Discover sources for a specific part revision (e.g. k9k engine, edc transmission).

    Uses part-centric search queries ("{part_id} engine problems") rather than
    model-centric ones. Sources are written to knowledge/sources/curated/part_{part_id}.yaml
    and then processed through the standard extraction + promotion pipeline.
    """
    from knowledge.parts.search_templates import templates_for_part
    from knowledge.process import run_part as process_run_part

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
        # For part-centric searches, only use owner clubs and Turkish forums as
        # specialist domains — generic car review sites (whatcar, carbuyer) return
        # off-brand content because they index all car models.
        _PART_SPECIALIST_DOMAINS = [
            "meganeownersclub.co.uk",
            "honestjohn.co.uk",
            "pistonheads.com",
            "donanimhaber.com",
        ]
        pages = _discover_web(
            templates, known_urls,
            make=part_id, model=part_type, gen_label=f"{part_id} {part_type}",
            max_per_query=max_web, specialist_domains=_PART_SPECIALIST_DOMAINS,
        )
        if pages:
            for p in pages:
                print(f"  [{p['tier']}] {p['url'][:75]}")
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


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(
        description="Auto-discover sources and run the full knowledge pipeline."
    )
    # Model-centric positional args (mutually exclusive with --part mode)
    parser.add_argument("make", nargs="?", help="Car make (model-centric mode)")
    parser.add_argument("model", nargs="?", help="Car model (model-centric mode)")
    parser.add_argument("gen", nargs="?", help="Generation key (model-centric mode)")
    # Part-centric mode
    parser.add_argument("--part", metavar="PART_ID",
                        help="Part ID for part-centric mode (e.g. k9k, edc, ea211)")
    parser.add_argument("--part-type", choices=["engine", "transmission"],
                        help="Part type (required with --part)")
    parser.add_argument("--fuel", default="",
                        choices=["", "diesel", "petrol"],
                        help="Fuel type hint for part-specific queries")
    # Shared flags
    parser.add_argument("--dry-run", action="store_true",
                        help="Discover only — print what would be added, no writes")
    parser.add_argument("--no-web", action="store_true", help="Skip Exa web search")
    parser.add_argument("--no-youtube", action="store_true", help="Skip YouTube search")
    parser.add_argument("--max-web", type=int, default=3)
    parser.add_argument("--max-yt", type=int, default=3)
    parser.add_argument("--max-sources", type=int, default=25)
    args = parser.parse_args()

    shared = dict(
        dry_run=args.dry_run,
        web=not args.no_web,
        youtube=not args.no_youtube,
        max_web=args.max_web,
        max_yt=args.max_yt,
        max_sources=args.max_sources,
    )

    if args.part:
        if not args.part_type:
            parser.error("--part requires --part-type")
        run_part(args.part.lower(), args.part_type, fuel=args.fuel, **shared)
    else:
        if not (args.make and args.model and args.gen):
            parser.error("model-centric mode requires make, model, and gen arguments")
        run(args.make.lower(), args.model.lower(), args.gen.lower(), **shared)


if __name__ == "__main__":
    main()
