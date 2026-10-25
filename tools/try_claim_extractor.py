#!/usr/bin/env python3
"""Try the cars claim extractor on one piece of text.

The extractor is `packs/cars/pipeline/extract.py`:

    text -> langextract (DeepSeek v4 flash, few-shot from gold.yaml)
         -> CandidateClaim (title, domain, severity, rationale, quote, ...)

It reads the whole text in overlapping 4,000-character chunks: the opening and
closing chunks always, a middle chunk only when the pack's signal gate says it
is worth paying for. Claims repeated by the overlap are de-duplicated. The
`--dry-run` shows the chunks and the gate's decision without calling a model.

    python tools/try_claim_extractor.py --file listing.txt
    python tools/try_claim_extractor.py --text "The thermostat housing on the 1.3 TCe cracks..."
    python tools/try_claim_extractor.py --file listing.txt --dry-run
    python tools/try_claim_extractor.py --file listing.txt --json

The live run needs DEEPSEEK_API_KEY in the environment or in `~/.kriko/env`
(`keys.load()` is called before the extractor module is imported, because that
module reads the variable at import time). `--dry-run` needs no key and spends
nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for entry in (ROOT / "src", ROOT):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))


def _text(args) -> str:
    if args.text:
        return args.text
    if args.file:
        return Path(args.file).read_text(encoding="utf-8", errors="replace")
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise SystemExit("give --text, --file, or pipe the source text on stdin")


def _dry_run(text: str) -> int:
    from packs.cars.pipeline.ledger.chunking import chunk_has_signal, chunk_text

    chunks = list(chunk_text(text))
    signal = [chunk for chunk in chunks if chunk_has_signal(chunk.text)]
    print(f"{len(text):,} characters -> {len(chunks)} chunk(s); "
          f"{len(signal)} carry a reliability signal")
    for chunk in chunks:
        kept = chunk_has_signal(chunk.text)
        tokens = len(chunk.text) // 4
        print(f"  chunk {chunk.index}: {len(chunk.text):,} chars ~{tokens:,} tokens "
              f"{'extract' if kept else 'skip (no signal)'}")
    print("\nThe extractor reads the whole text in overlapping chunks: the "
          "opening and closing chunks always, a middle chunk only when the "
          "signal gate says it is worth paying for.")
    return 0


def main() -> int:
    # Windows consoles default to cp1252, and a Turkish quote is a normal
    # result, not an error. Print the extractor's own words rather than dying
    # on the last line of a successful run.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--text", help="the source text")
    source.add_argument("--file", help="a UTF-8 text file")
    parser.add_argument("--url", default="", help="where the text came from, for the record")
    parser.add_argument("--site", default="local text", help="site or channel name")
    parser.add_argument("--dry-run", action="store_true",
                        help="show the chunks and signal gate without calling a model")
    parser.add_argument("--json", action="store_true", help="print claims as JSON")
    args = parser.parse_args()

    text = _text(args)
    if not text.strip():
        raise SystemExit("the source text is empty")
    if args.dry_run:
        return _dry_run(text)

    from app import keys

    keys.load()
    from packs.cars.pipeline.extract import extract_claims
    from packs.cars.pipeline.sources.base import Document

    try:
        claims = extract_claims(Document(
            text=text, url=args.url, site_or_channel=args.site))
    except RuntimeError as error:
        if "DEEPSEEK_API_KEY" in str(error):
            print("No DEEPSEEK_API_KEY is visible.\n"
                  "Put it in ~/.kriko/env or export it, then run this again.\n"
                  "`--dry-run` needs no key and spends nothing.", file=sys.stderr)
            return 2
        raise

    if args.json:
        print(json.dumps([claim.model_dump() for claim in claims], indent=2, ensure_ascii=False))
        return 0

    print(f"{len(claims)} claim(s)")
    for claim in claims:
        grounded = "quote grounded" if claim.quote_grounded else "quote not aligned"
        print(f"\n[{claim.severity}] {claim.title}")
        print(f"  domain: {claim.domain} · {grounded}")
        print(f"  why:    {claim.rationale}")
        print(f"  check:  {claim.inspection_advice}")
        if claim.engine_or_variant_hint:
            print(f"  variant:{claim.engine_or_variant_hint}")
        print(f"  quote:  {claim.quote[:300]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
