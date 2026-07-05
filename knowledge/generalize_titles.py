"""generalize_titles.py — rewrite DTC-litany / verbose-paragraph titles into
brief, general chronic-pattern titles.

Per user feedback (2026-07-04): "data quality and mismatches are horrible...
not P0312 fail may cause x, we need just injector problems with brief
descriptions." Root cause fixed in extract.py's prompt for future runs; this
is the retroactive fix for already-written claims.

Only rewrites the `title` field. `rationale`/`inspection_advice`/`quote`/
`sources` are untouched — the diagnostic codes move into inspection_advice
(appended, not fabricated) so a buyer's mechanic can still verify them.

Scope (2026-07-04): 14 servable (review/verified) claims across the whole
catalog match `title_has_dtc_code` or `title_is_verbose` — this is a
GENERALIZE-only script. It does NOT touch DROP candidates (factually
impossible, cross-brand, non-automotive) — those need a human merge/delete
decision, not a rewrite (see knowledge/gold/gold.yaml verdict_notes and the
project memory's "Session 2026-07-04" section for the specific claims found).

Usage:
    python -m knowledge.generalize_titles              # dry run — preview only
    python -m knowledge.generalize_titles --apply       # rewrite + write
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

import yaml
from dotenv import load_dotenv

from knowledge.stoplists import DTC_CODE_RE, title_has_dtc_code, title_is_verbose

load_dotenv()

REPO_ROOT = Path(__file__).parent.parent
PARTS_DIR = REPO_ROOT / "backend" / "data" / "parts"
CLAIMS_DIR = REPO_ROOT / "backend" / "data" / "claims"

MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
_MODEL = "ministral-8b-latest"


def _needs_generalization(claim: dict) -> bool:
    if claim.get("status") not in ("review", "verified"):
        return False
    title = str(claim.get("title", "") or "")
    return title_has_dtc_code(title) or title_is_verbose(title)


def _parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text.strip())


def _generalize_title(claim: dict) -> str:
    """One Mistral call: rewrite the title as a brief, general chronic
    pattern with the engine/variant code kept as anchor, DTC codes stripped."""
    from mistralai.client import Mistral

    client = Mistral(api_key=MISTRAL_API_KEY)
    prompt = (
        "Rewrite this car-reliability claim's TITLE only. Rules:\n"
        "- Brief phrase, under 12 words.\n"
        "- Describe the GENERAL failure in plain words (e.g. 'injector fouling', "
        "'random multi-cylinder misfire') — NEVER include a raw diagnostic "
        "trouble code (P0300, P17BF, DTC numbers) in the title.\n"
        "- Keep any engine/transmission code or variant anchor from the "
        "current title/rationale (e.g. 'K9K', 'DQ200', '1.5 dCi') — do not "
        "make it generic, just brief.\n"
        "- Do not restate the rationale; the title is a short label, not a sentence.\n\n"
        f"Current title: {claim.get('title', '')}\n"
        f"Rationale: {claim.get('rationale', '')}\n\n"
        'Return ONLY valid JSON: {"title": "..."}'
    )
    messages = [
        {"role": "system", "content": "You write brief, precise titles for car reliability claims."},
        {"role": "user", "content": prompt},
    ]
    last_exc: Exception = RuntimeError("generalization failed after retries")
    for attempt in range(3):
        try:
            response = client.chat.complete(
                model=_MODEL,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=256,
            )
            raw = response.choices[0].message.content
            return _parse_json(raw)["title"]
        except Exception as exc:
            last_exc = exc
            if "429" in str(exc) and attempt < 2:
                time.sleep(2 ** attempt * 5)
                continue
            raise
    raise last_exc


def _append_codes_to_inspection_advice(claim: dict, old_title: str) -> None:
    codes = sorted(set(DTC_CODE_RE.findall(old_title)))
    if not codes:
        return
    advice = claim.get("inspection_advice", "") or ""
    code_note = f"Diagnostic code(s) to check for: {', '.join(codes)}."
    if code_note not in advice:
        claim["inspection_advice"] = (advice + " " + code_note).strip()


def _fix_file(path: Path, apply: bool) -> list[tuple[str, str, str]]:
    data = yaml.safe_load(path.read_text()) or {}
    claims = data.get("claims") if isinstance(data, dict) and "claims" in data else data
    if not isinstance(claims, list):
        return []

    changed: list[tuple[str, str, str]] = []
    file_dirty = False
    for claim in claims:
        if not isinstance(claim, dict) or not _needs_generalization(claim):
            continue
        old_title = claim["title"]
        if not apply:
            changed.append((claim.get("claim_key", ""), old_title, "[preview only — pass --apply]"))
            continue
        try:
            new_title = _generalize_title(claim)
        except Exception as exc:
            changed.append((claim.get("claim_key", ""), old_title, f"[FAILED: {exc}]"))
            continue
        _append_codes_to_inspection_advice(claim, old_title)
        claim["title"] = new_title
        changed.append((claim.get("claim_key", ""), old_title, new_title))
        file_dirty = True

    if file_dirty and apply:
        if isinstance(data, dict) and "claims" in data:
            data["claims"] = claims
            path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False))
        else:
            path.write_text(yaml.dump(claims, allow_unicode=True, sort_keys=False))

    return changed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Rewrite + write changes (default: preview only)")
    args = parser.parse_args()

    if args.apply and not MISTRAL_API_KEY:
        print("ERROR: MISTRAL_API_KEY not set — cannot generalize.")
        return

    print(f"{'APPLYING' if args.apply else 'PREVIEW (dry run)'}\n")

    total = 0
    for base_dir in (PARTS_DIR, CLAIMS_DIR):
        if not base_dir.exists():
            continue
        for path in sorted(base_dir.glob("**/*.yaml")):
            changed = _fix_file(path, args.apply)
            total += len(changed)
            if changed:
                print(f"  {path.relative_to(REPO_ROOT)}:")
                for key, old, new in changed:
                    print(f"      {key!r}:")
                    print(f"          before: {old!r}")
                    print(f"          after:  {new!r}")

    print(f"\n  TOTAL: {total} claim(s) {'generalized' if args.apply else 'flagged'}")
    if not args.apply:
        print("\nDry run — no API calls made, no files written. Re-run with --apply to rewrite.")


if __name__ == "__main__":
    main()
