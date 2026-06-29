#!/usr/bin/env python3
"""Interactive CLI tool to review, edit, and promote/reject claims in claims YAML files.

Runs offline and syncs back to DB + Docker container automatically.
"""

import argparse
import subprocess
import sys
from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).parent.parent
DATA_DIR = REPO_ROOT / "backend" / "data"


class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


def select_claims_file() -> Path:
    claims_files = list((DATA_DIR / "claims").glob("*.yaml"))
    if not claims_files:
        print(f"{Colors.FAIL}No claims YAML files found in {DATA_DIR / 'claims'}{Colors.ENDC}")
        sys.exit(1)
    if len(claims_files) == 1:
        return claims_files[0]

    print(f"{Colors.BOLD}Select a claims file to review:{Colors.ENDC}")
    for idx, path in enumerate(claims_files, 1):
        print(f"  {idx}. {path.name}")
    while True:
        try:
            choice = input(f"Select choice [1-{len(claims_files)}]: ").strip()
            val = int(choice)
            if 1 <= val <= len(claims_files):
                return claims_files[val - 1]
        except ValueError:
            pass
        print("Invalid choice, try again.")


def print_claim(claim: dict, index: int, total: int):
    print("\n" + "=" * 80)
    print(f"{Colors.BOLD}{Colors.HEADER}Claim [{index}/{total}]: {claim.get('title')}{Colors.ENDC}")
    print(f"  {Colors.BOLD}ID:{Colors.ENDC} {claim.get('id')}")
    print(f"  {Colors.BOLD}Domain:{Colors.ENDC} {Colors.CYAN}{claim.get('domain')}{Colors.ENDC} | "
          f"{Colors.BOLD}Severity:{Colors.ENDC} {Colors.WARNING}{claim.get('severity')}{Colors.ENDC} | "
          f"{Colors.BOLD}Current Status:{Colors.ENDC} {Colors.BLUE}{claim.get('status')}{Colors.ENDC}")
    print(f"  {Colors.BOLD}Confidence:{Colors.ENDC} {claim.get('confidence')}")
    print(f"  {Colors.BOLD}Rationale:{Colors.ENDC}\n    {claim.get('rationale')}")
    print(f"  {Colors.BOLD}Inspection Advice:{Colors.ENDC}\n    {claim.get('inspection_advice')}")

    variants = claim.get("variants") or []
    print(f"  {Colors.BOLD}Grounded Variants ({len(variants)}):{Colors.ENDC}")
    for v in variants:
        print(f"    - {v.get('variant_id')} ({v.get('grounding_note')})")

    sources = claim.get("sources") or []
    print(f"  {Colors.BOLD}Sources ({len(sources)}):{Colors.ENDC}")
    for s in sources:
        print(f"    - [{s.get('tier')}] {s.get('source_url')} ({s.get('site_or_channel')})")
        if s.get("quote"):
            # Clean up newlines for display
            quote = s.get("quote").replace("\n", " ").strip()
            print(f"      Quote: \"{quote[:120]}...\"")
    print("=" * 80)


def edit_claim(claim: dict) -> bool:
    print(f"\n{Colors.BOLD}Editing Claim: {claim.get('title')}{Colors.ENDC}")
    changed = False

    title = input(f"New Title [{claim.get('title')}]: ").strip()
    if title:
        claim['title'] = title
        changed = True

    severity = input(f"New Severity [{claim.get('severity')}]: ").strip()
    if severity:
        claim['severity'] = severity
        changed = True

    rationale = input(f"New Rationale [{claim.get('rationale')}]: ").strip()
    if rationale:
        claim['rationale'] = rationale
        changed = True

    advice = input(f"New Inspection Advice [{claim.get('inspection_advice')}]: ").strip()
    if advice:
        claim['inspection_advice'] = advice
        changed = True

    return changed


def prompt_action() -> str:
    while True:
        choice = input(
            f"Actions: [{Colors.GREEN}v{Colors.ENDC}]erified (promote), "
            f"[{Colors.FAIL}r{Colors.ENDC}]ejected, "
            f"[{Colors.BLUE}h{Colors.ENDC}]eld, "
            f"[{Colors.WARNING}e{Colors.ENDC}]dit, "
            f"[s]kip, [q]uit: "
        ).strip().lower()
        if choice in ['v', 'r', 'h', 'e', 's', 'q']:
            return choice
        print("Invalid choice, please select v, r, h, e, s, or q.")


def sync_db():
    print(f"\n{Colors.BOLD}Syncing changes to database via Docker...{Colors.ENDC}")
    try:
        subprocess.run(
            ["docker", "compose", "-f", "deploy/docker-compose.yml", "exec", "-T", "api", "python", "-m", "backend.sync"],
            check=True, cwd=REPO_ROOT
        )
        print(f"{Colors.GREEN}Sync successful!{Colors.ENDC}")
        return
    except Exception as e:
        print(f"{Colors.WARNING}Docker exec sync failed, trying container restart... ({e}){Colors.ENDC}")

    try:
        subprocess.run([
            "docker", "compose", "-f", "deploy/docker-compose.yml", "restart", "api"
        ], check=True, cwd=REPO_ROOT)
        print(f"{Colors.GREEN}FastAPI container restarted and synced successfully!{Colors.ENDC}")
    except Exception as e:
        print(f"{Colors.FAIL}Docker container restart failed, trying local sync... ({e}){Colors.ENDC}")
        try:
            subprocess.run([sys.executable, "-m", "backend.sync"], check=True, cwd=REPO_ROOT)
            print(f"{Colors.GREEN}Local sync successful!{Colors.ENDC}")
        except Exception as e2:
            print(f"{Colors.FAIL}Local sync failed: {e2}{Colors.ENDC}")
            print("Run manually: docker compose -f deploy/docker-compose.yml exec api python -m backend.sync")


def main():
    parser = argparse.ArgumentParser(description="Interactive tool to review and promote claims.")
    parser.add_argument("--status", choices=["review", "held", "all"], default="review",
                        help="Filter claims by status (default: review)")
    args = parser.parse_args()

    claims_file = select_claims_file()
    print(f"\nLoading claims from: {Colors.CYAN}{claims_file.name}{Colors.ENDC}")

    with open(claims_file) as f:
        claims = yaml.safe_load(f) or []

    # Filter claims to review
    target_statuses = [args.status] if args.status != "all" else ["review", "held"]
    to_review = [c for c in claims if c.get("status") in target_statuses]

    if not to_review:
        print(f"No claims found with status in {target_statuses} in {claims_file.name}.")
        return

    print(f"Found {len(to_review)} claim(s) with status in {target_statuses} to review.")

    dirty = False
    index = 1
    total = len(to_review)

    for claim in to_review:
        print_claim(claim, index, total)
        index += 1

        action = prompt_action()
        if action == 'q':
            break

        if action == 's':
            continue

        if action == 'e':
            if edit_claim(claim):
                dirty = True
            # Prompt again for status change after edit
            action = prompt_action()
            if action == 'q':
                break
            if action == 's':
                continue

        if action == 'v':
            claim['status'] = 'verified'
            claim['promoted_by'] = 'human'
            print(f"{Colors.GREEN}Status updated to verified.{Colors.ENDC}")
            dirty = True
        elif action == 'r':
            claim['status'] = 'rejected'
            print(f"{Colors.FAIL}Status updated to rejected.{Colors.ENDC}")
            dirty = True
        elif action == 'h':
            claim['status'] = 'held'
            print(f"{Colors.BLUE}Status updated to held.{Colors.ENDC}")
            dirty = True

    if dirty:
        print(f"\nSaving changes to {claims_file.name}...")
        with open(claims_file, "w") as f:
            yaml.dump(claims, f, allow_unicode=True, sort_keys=False)
        print(f"{Colors.GREEN}Changes saved successfully!{Colors.ENDC}")

        # Ask to sync
        sync_choice = input("Do you want to sync changes to the database and restart API container now? [y/N]: ").strip().lower()
        if sync_choice in ['y', 'yes']:
            sync_db()
    else:
        print("\nNo changes to save.")


if __name__ == "__main__":
    main()
