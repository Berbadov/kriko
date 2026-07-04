"""translate_claims.py — retroactive English translation of claim text.

knowledge.extract's SYSTEM_PROMPT never mandated an output language, so
title/rationale/inspection_advice sometimes came back in the source
language (German from what-breaks.com, Turkish from Turkish-language repair
sites) instead of the intended convention: English claim text + original-
language `quote` kept verbatim for sourcing authenticity. Confirmed live in
megane4_body.yaml ("Kupplungsüberhitzung", "IBS (Akü Sensörü) Arızalanması",
etc.) — a buyer who doesn't read German/Turkish gets nothing from these,
which defeats the point of showing them at all.

extract.py's prompt now requires English output for future extractions;
this script fixes already-written claims. Only title/rationale/
inspection_advice are translated — `sources[].quote` is left untouched
(same original-language-verbatim convention as always).

Detection is a cheap heuristic (knowledge.stoplists.is_likely_non_english,
zero cost) run in both dry-run and apply mode. Translation itself costs one
Mistral call per flagged claim, so only --apply spends anything.

Usage:
    python -m knowledge.translate_claims              # dry run — list only
    python -m knowledge.translate_claims --apply       # translate + write
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

from knowledge.stoplists import is_likely_non_english

load_dotenv()

REPO_ROOT = Path(__file__).parent.parent
PARTS_DIR = REPO_ROOT / "backend" / "data" / "parts"
CLAIMS_DIR = REPO_ROOT / "backend" / "data" / "claims"

MISTRAL_API_KEY = os.environ.get("MISTRAL_API_KEY", "")
_MODEL = "ministral-8b-latest"


def _needs_translation(claim: dict) -> bool:
    """Flag on the TITLE alone, not the combined text.

    Rationale legitimately quotes a source term in parentheses as part of a
    well-formed English sentence (e.g. "...attributed to potential catalytic
    converter clogging. The mention of 'katalitik konvertör tıkalı olabilir'
    (catalytic converter may be clogged) supports this defect.") — flagging
    on combined text over-triggered on these, which don't need translation.
    A non-English TITLE, by contrast, was consistently wholesale-foreign in
    every real case found ("Kupplungsüberhitzung", "IBS (Akü Sensörü)
    Arızalanması") — title is also the single most user-visible field.

    Parenthetical asides are stripped before checking: a legitimate original-
    language technical gloss in parens ("...2.0 TDI PD (Pump-Düse) engines
    rated at 170 horsepower") is intentional and correct per this dataset's
    convention, not untranslated content — checking it anyway caused a real
    regression (re-flagged an already-fine title, and the LLM "translation"
    ballooned it into a 490-char paragraph duplicating the rationale).
    """
    title = str(claim.get("title", "") or "")
    core = re.sub(r"\([^)]*\)", "", title)
    return is_likely_non_english(core)


def _parse_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text.strip())


def _translate_fields(title: str, rationale: str, inspection_advice: str) -> dict:
    """One Mistral call: translate the three English-facing fields, preserve meaning exactly."""
    from mistralai.client import Mistral

    client = Mistral(api_key=MISTRAL_API_KEY)
    prompt = (
        "Translate the following car-reliability claim fields into natural, plain English. "
        "Preserve technical meaning exactly — engine/transmission codes, part names, and "
        "failure modes must not change. Do not add or remove information, do not summarize.\n\n"
        f"title: {title}\n"
        f"rationale: {rationale}\n"
        f"inspection_advice: {inspection_advice}\n\n"
        'Return ONLY valid JSON: {"title": "...", "rationale": "...", "inspection_advice": "..."}'
    )
    messages = [
        {
            "role": "system",
            "content": "You are a precise technical translator for automotive reliability claims.",
        },
        {"role": "user", "content": prompt},
    ]
    last_exc: Exception = RuntimeError("translation failed after retries")
    for attempt in range(3):
        try:
            response = client.chat.complete(
                model=_MODEL,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=1024,
            )
            raw = response.choices[0].message.content
            return _parse_json(raw)
        except Exception as exc:
            last_exc = exc
            if "429" in str(exc) and attempt < 2:
                time.sleep(2 ** attempt * 5)
                continue
            raise
    raise last_exc


def _fix_file(path: Path, apply: bool) -> list[tuple[str, str, str]]:
    """Return [(claim_key_or_title, old_title, new_title_or_'[flagged]'), ...]."""
    data = yaml.safe_load(path.read_text()) or {}
    claims = data.get("claims") if isinstance(data, dict) and "claims" in data else data
    if not isinstance(claims, list):
        return []

    changed: list[tuple[str, str, str]] = []
    file_dirty = False
    for claim in claims:
        if not isinstance(claim, dict) or not _needs_translation(claim):
            continue
        label = claim.get("claim_key") or claim.get("title", "")
        old_title = claim.get("title", "")
        if not apply:
            changed.append((label, old_title, "[flagged for translation]"))
            continue
        try:
            translated = _translate_fields(
                claim.get("title", ""), claim.get("rationale", ""), claim.get("inspection_advice", "")
            )
        except Exception as exc:
            changed.append((label, old_title, f"[translation FAILED: {exc}]"))
            continue
        claim["title"] = translated.get("title", claim["title"])
        claim["rationale"] = translated.get("rationale", claim.get("rationale", ""))
        claim["inspection_advice"] = translated.get(
            "inspection_advice", claim.get("inspection_advice", "")
        )
        changed.append((label, old_title, claim["title"]))
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
    parser.add_argument("--apply", action="store_true", help="Translate + write changes (default: dry run, zero API calls)")
    args = parser.parse_args()

    if args.apply and not MISTRAL_API_KEY:
        print("ERROR: MISTRAL_API_KEY not set — cannot translate.")
        return

    print(f"{'APPLYING (calls Mistral per flagged claim)' if args.apply else 'DRY RUN — zero API calls'}\n")

    total = 0
    for base_dir in (PARTS_DIR, CLAIMS_DIR):
        if not base_dir.exists():
            continue
        for path in sorted(base_dir.glob("**/*.yaml")):
            changed = _fix_file(path, args.apply)
            total += len(changed)
            if changed:
                print(f"  {path.relative_to(REPO_ROOT)}:")
                for label, old, new in changed:
                    print(f"      {label!r}: {old!r} -> {new!r}")

    print(f"\n  TOTAL: {total} claim(s) {'translated' if args.apply else 'flagged'}")
    if not args.apply:
        print("\nDry run — no API calls made, no files written. Re-run with --apply to translate.")


if __name__ == "__main__":
    main()
