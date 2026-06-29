"""extract_fitment.py — LLM-structured extraction of fitment data.

Fetches fitment information from Wikipedia + TecDoc for a given engine or
transmission code, then uses an LLM (Mistral, temp=0, strict schema) to extract
structured fitment rows: which car model/year uses this engine/gearbox code.

The output is cached to a YAML file to make re-runs cost-free. Human reviews
the output before committing as authoritative fitment data.

Usage:
    python -m knowledge.fitment.extract_fitment --part k9k --type engine
    python -m knowledge.fitment.extract_fitment --part edc --type transmission
    python -m knowledge.fitment.extract_fitment --part h5h --type engine --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

REPO_ROOT    = Path(__file__).parent.parent.parent
CACHE_DIR    = Path(__file__).parent / "cache"
PARTS_DIR    = REPO_ROOT / "backend" / "data" / "parts"

# Wikipedia queries per part_id — engine engineering articles have reliable fitment tables.
WIKIPEDIA_QUERIES: dict[str, str] = {
    "k9k":    "Renault K9K engine",
    "h5f":    "Renault H5F engine TCe",
    "h5h":    "Renault H5H engine TCe 1.3",
    "r9m":    "Renault R9M engine dCi",
    "ea111":  "Volkswagen EA111 engine",
    "ea211":  "Volkswagen EA211 engine",
    "edc":    "Renault EDC transmission dual clutch",
    "dq200":  "Volkswagen DQ200 transmission DSG",
    "dq250":  "Volkswagen DQ250 transmission DSG",
}


def _cache_path(part_id: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / f"fitment_{part_id}.json"


class FitmentRow:
    """Structured fitment record extracted from source text."""
    def __init__(self, make: str, model: str, year_from: int, year_to: int | None,
                 engine_family: str | None, transmission_code: str | None,
                 displacement_cc: int | None, power_hp: int | None, notes: str = ""):
        self.make = make
        self.model = model
        self.year_from = year_from
        self.year_to = year_to
        self.engine_family = engine_family
        self.transmission_code = transmission_code
        self.displacement_cc = displacement_cc
        self.power_hp = power_hp
        self.notes = notes

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


def _llm_extract_fitment(text: str, part_id: str, part_type: str) -> list[dict]:
    """Send source text to LLM and extract structured fitment rows."""
    api_key = os.getenv("MISTRAL_API_KEY")
    if not api_key:
        log.warning("MISTRAL_API_KEY not set — cannot extract fitment")
        return []

    from mistralai import Mistral

    client = Mistral(api_key=api_key)

    system_prompt = (
        "You are a precise automotive data extractor. Extract fitment records from the "
        "provided text — that is, which car models and years use this specific engine or "
        "transmission code. Return a JSON object with key 'fitment' containing a list of "
        "records. Each record must have: make (brand name), model (model name), year_from "
        "(int), year_to (int or null), displacement_cc (int or null), power_hp (int or null), "
        "notes (brief description). Only extract facts explicitly stated in the text. "
        "Do not invent or infer. If you are unsure, omit the field."
    )

    user_prompt = (
        f"Extract fitment data for part_id={part_id!r} (type: {part_type}) from this text:\n\n"
        f"{text[:6000]}"
    )

    try:
        resp = client.chat.complete(
            model="ministral-8b-latest",
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        raw = resp.choices[0].message.content
        data = json.loads(raw)
        return data.get("fitment", [])
    except Exception as exc:
        log.warning("LLM fitment extraction failed: %s", exc)
        return []


def run(part_id: str, part_type: str, dry_run: bool = False) -> list[dict]:
    """Fetch sources, extract fitment, cache result, return rows."""
    cache = _cache_path(part_id)
    if cache.exists():
        print(f"  Loading cached fitment for {part_id} from {cache}")
        return json.loads(cache.read_text())

    from knowledge.fitment.sources.wikipedia import fetch_engine_article

    rows: list[dict] = []
    query = WIKIPEDIA_QUERIES.get(part_id)
    if query:
        print(f"  Fetching Wikipedia: {query!r}")
        text = fetch_engine_article(query)
        if text:
            print(f"  Extracting fitment from {len(text)} chars…")
            rows.extend(_llm_extract_fitment(text, part_id, part_type))

    if not rows:
        print(f"  No fitment rows extracted for {part_id}")

    if dry_run:
        print(f"  DRY RUN — would cache {len(rows)} row(s). No writes.")
        return rows

    cache.write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    print(f"  Cached {len(rows)} fitment row(s) to {cache}")
    return rows


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Extract fitment data for a part.")
    parser.add_argument("--part", required=True, help="Part ID (e.g. k9k, edc, ea211)")
    parser.add_argument("--type", dest="part_type", required=True,
                        choices=["engine", "transmission"],
                        help="Part type")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and extract but do not write cache")
    args = parser.parse_args()

    rows = run(args.part, args.part_type, dry_run=args.dry_run)
    if rows:
        print(f"\nExtracted {len(rows)} fitment row(s):")
        for r in rows:
            print(f"  {r.get('make', '?')} {r.get('model', '?')} "
                  f"{r.get('year_from', '?')}-{r.get('year_to', 'present')} "
                  f"{r.get('displacement_cc', '?')}cc {r.get('power_hp', '?')}hp")


if __name__ == "__main__":
    main()
