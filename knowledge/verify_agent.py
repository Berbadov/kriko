#!/usr/bin/env python3
"""verify_agent.py — automated offline verification agent.

Searches the web for unverified (review/held) claims using Exa, extracts content,
runs LLM gates (support/refute), and automatically promotes corroborated claims
to 'verified' to scale Kriko without manual human review.

Usage:
    python -m knowledge.verify_agent renault megane 4
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlparse
import yaml
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).parent.parent
DATA_DIR = REPO_ROOT / "backend" / "data"

TIER_WEIGHT = {
    "A": 1.0,
    "B": 0.5,
    "C": 0.34,
}


def _calculate_score(sources: list[dict]) -> float:
    score = 0.0
    for s in sources:
        tier = s.get("tier", "C")
        score += TIER_WEIGHT.get(tier, 0.34)
    return score


def run(make: str, model: str, gen: str, dry_run: bool = False) -> None:
    from exa_py import Exa
    import trafilatura
    from knowledge.judge import gate_support, gate_refute
    from knowledge.sources.curated import _fetch_html
    from knowledge.auto import _tier_for_url

    exa_key = os.getenv("EXA_API_KEY")
    if not exa_key:
        print("ERROR: EXA_API_KEY environment variable not set.")
        sys.exit(1)
    
    mistral_key = os.getenv("MISTRAL_API_KEY")
    if not mistral_key:
        print("ERROR: MISTRAL_API_KEY environment variable not set.")
        sys.exit(1)

    exa = Exa(api_key=exa_key)

    # 1. Resolve claims YAML file
    claims_path = DATA_DIR / "claims" / f"{make}_{model}_{gen}.yaml"
    if not claims_path.exists():
        # Try fallback matching
        matches = list((DATA_DIR / "claims").glob(f"{make}_{model}*.yaml"))
        if len(matches) == 1:
            claims_path = matches[0]
        else:
            print(f"ERROR: Could not find claims YAML file for {make} {model} {gen}.")
            sys.exit(1)

    print(f"Loading claims from: {claims_path}")
    with open(claims_path) as f:
        claims = yaml.safe_load(f) or []

    unverified_claims = [c for c in claims if c.get("status") in ("review", "held")]
    if not unverified_claims:
        print("No unverified (review/held) claims to process.")
        return

    print(f"Found {len(unverified_claims)} unverified claim(s) to process.")
    dirty = False

    for idx, claim in enumerate(unverified_claims, 1):
        print(f"\n[{idx}/{len(unverified_claims)}] Verifying claim: {claim['title']}")
        print(f"  Current Status: {claim['status']} | Severity: {claim['severity']}")
        
        # 2. Build search query
        # Format a clear query targeting the failure mode and the car model
        query = f"{make.title()} {model.title()} {claim['title']} problem reliability issues"
        print(f"  Searching Exa: {query!r}")

        # Gather existing URLs to exclude
        existing_urls = {s.get("source_url") for s in claim.get("sources", [])}
        exclude_domains = ["sahibinden.com", "arabam.com", "pinterest.com", "ebay.com"]

        try:
            resp = exa.search(
                query,
                num_results=4,
                exclude_domains=exclude_domains,
            )
        except Exception as exc:
            print(f"  Exa search failed: {exc}")
            continue

        valid_results = [r for r in resp.results if r.url not in existing_urls]
        if not valid_results:
            print("  No new search results found.")
            continue

        print(f"  Found {len(valid_results)} new search result(s). Checking content...")
        
        new_sources_added = []
        for r in valid_results:
            url = r.url
            host = urlparse(url).netloc.lower().removeprefix("www.")
            print(f"    - Fetching {url[:60]}... ", end="", flush=True)

            html = _fetch_html(url)
            if not html:
                print("failed to fetch HTML")
                continue
            
            text = trafilatura.extract(html, include_comments=False, include_tables=False)
            if not text:
                print("failed to extract text")
                continue

            print(f"{len(text):,} chars ", end="", flush=True)

            # 3. LLM Gate Validation
            try:
                support = gate_support(claim["title"], claim.get("rationale", ""), text)
                if not support.passed:
                    print("→ gate_support FAILED")
                    continue

                refute = gate_refute(claim["title"], claim.get("rationale", ""), text)
                if not refute.passed:
                    print("→ gate_refute FAILED (claim contradicted)")
                    continue
                
                # Verified!
                tier = _tier_for_url(url)
                print(f"→ PASSED (corroborating source found! Tier {tier})")
                new_sources_added.append({
                    "tier": tier,
                    "source_url": url,
                    "source_domain": host,
                    "site_or_channel": host,
                    "quote": support.reason,
                    "independent": True,
                })
            except Exception as exc:
                print(f"→ gate validation failed: {exc}")

        if new_sources_added:
            dirty = True
            claim.setdefault("sources", []).extend(new_sources_added)
            
            # Recalculate score
            old_score = _calculate_score(claim.get("sources", [])[:-len(new_sources_added)])
            new_score = _calculate_score(claim["sources"])
            print(f"  Corroboration Score: {old_score:.2f} → {new_score:.2f}")

            # 4. Promotion logic
            # High-severity claims are critical, so they require score >= 1.0 (e.g. Tier A or 2x Tier B) to auto-verify.
            # Normal/medium/low severity claims auto-verify with score >= 0.5.
            threshold = 1.0 if claim["severity"] == "high" else 0.5
            
            if new_score >= threshold:
                claim["status"] = "verified"
                claim["promoted_by"] = "auto_verified_agent"
                claim["confidence"] = round(min(0.9, max(0.6, new_score / 2)), 2)
                print(f"  PROMOTED to 'verified'! Confidence set to {claim['confidence']}")
            else:
                # If score increased but not past threshold, we upgrade held -> review for visibility
                if claim["status"] == "held" and new_score >= 0.34:
                    claim["status"] = "review"
                    claim["confidence"] = round(min(0.9, max(0.6, new_score / 2)), 2)
                    print(f"  UPGRADED status to 'review'.")

    # 5. Write back to claims YAML
    if dirty:
        if dry_run:
            print("\nDRY RUN — no changes written to disk.")
        else:
            print(f"\nWriting changes back to {claims_path}...")
            with open(claims_path, "w") as f:
                yaml.dump(claims, f, allow_unicode=True, sort_keys=False)
            print("Changes written successfully!")

            # Sync with database
            print("\nSyncing to DB…")
            try:
                import subprocess
                subprocess.run(
                    ["docker", "compose", "-f", "deploy/docker-compose.yml", "exec", "-T", "api", "python", "-m", "backend.sync"],
                    check=True, cwd=REPO_ROOT
                )
                print("Sync successful!")
            except Exception as exc:
                print(f"Docker exec sync failed, trying container restart... ({exc})")
                try:
                    subprocess.run(
                        ["docker", "compose", "-f", "deploy/docker-compose.yml", "restart", "api"],
                        check=True, cwd=REPO_ROOT
                    )
                    print("FastAPI container restarted successfully!")
                except Exception as exc2:
                    print(f"Docker restart failed, trying local sync... ({exc2})")
                    try:
                        subprocess.run([sys.executable, "-m", "backend.sync"], check=True, cwd=REPO_ROOT)
                        print("Local sync successful!")
                    except Exception as exc3:
                        print(f"Local sync failed: {exc3}")
                        print("Run manually: docker compose -f deploy/docker-compose.yml exec api python -m backend.sync")
    else:
        print("\nNo claims were promoted or updated.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Automated web verification agent for unverified claims."
    )
    parser.add_argument("make", help="Car make, e.g. renault, toyota")
    parser.add_argument("model", help="Car model, e.g. megane, corolla")
    parser.add_argument("gen", help="Generation key matching variants filename, e.g. 4, e210")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run verification checks but do not update claims YAML or database",
    )
    args = parser.parse_args()
    run(
        args.make.lower(),
        args.model.lower(),
        args.gen.lower(),
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
