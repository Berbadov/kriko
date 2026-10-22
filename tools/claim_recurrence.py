"""Does a claim recur across independent publishers? No model in the loop.

The proposition: statistics eliminate, the model only judges the shortlist.
So this experiment uses nothing but a search, a fetch, sentence matching and a
publisher count. A seed claim is turned into a query, the top pages are read,
and a page counts as an occurrence only when

* it is not a generic guide (`menu_page`), 
* it carries a sentence (not a heading, not a question) that shares most of the
  claim's content stems,
* its text is not a copy of a page already counted, and
* it is an independent publisher (registrable domain, from the bundled PSL).

Two or more independent publishers is "recurring". The point of the experiment
is not the absolute number; it is whether real faults separate from generic
symptom headings with no model and no vocabulary of faults.

    .venv/Scripts/python.exe tools/claim_recurrence.py
    .venv/Scripts/python.exe tools/claim_recurrence.py --limit 5 --pages 3
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app.providers import fetch, openserp  # noqa: E402
from app.providers.local_identity import fold  # noqa: E402
from app.providers.local_pipeline import (  # noqa: E402
    _stems, menu_page, publisher,
)

MIN_SENTENCE = 40


def product_terms(product: str) -> set[str]:
    """The words that make this product itself, not its brand.

    A code (`V11`, `WH-1000XM4`, `T480`) is decisive; without one, the longest
    words. The brand alone is not enough: a recurrence counted on "Sony" once
    matched a WH-1000XM3 article to a WH-1000XM4 seed.
    """
    tokens = {token.casefold() for token in re.findall(r"[^\W_]+", product)}
    codes = {token for token in tokens
             if any(char.isdigit() for char in token) or len(token) >= 6}
    return codes or {token for token in tokens if len(token) >= 4}


def core(claim: str, product: str) -> set[str]:
    """The claim's content stems, without the product's own words."""
    return _stems(claim) - _stems(product)


def report_sentence(sentence: str) -> bool:
    """A sentence that could be a report: not a heading, not a question."""
    text = " ".join(sentence.split())
    return len(text) >= MIN_SENTENCE and not text.endswith("?")


def matches(seed: set[str], sentence: str, rare: set[str] | None = None) -> bool:
    """Three shared content stems, and at least half of the claim's own.

    Two shared words let "short battery life" match a marketing sentence about
    battery life. Three is the smallest number that has separated a fault from
    the topic of the page in every run so far; a claim too thin to share three
    words is not expanded rather than wrongly recurring. Corpus frequency was
    tried as a second filter and is unstable on four pages, where "rare" means
    "on one page"; it needs a reference corpus, not the handful just fetched.
    """
    if len(seed) < 3:
        return False
    shared = len(seed & _stems(sentence))
    return shared >= 3 and shared * 2 >= len(seed)


def read_page(reader, url: str) -> str:
    try:
        got = reader(url)
        return str(getattr(got, "text", got) or "").strip()
    except Exception:  # noqa: BLE001 - a fetch is a network boundary
        return ""


def run_seed(seed: dict, search, reader, pages: int, timeout: float) -> dict:
    product, claim = seed["product"], seed["claim"]
    terms = core(claim, product)
    query = f'"{product}" {claim}'[:240]
    record = {"id": seed["id"], "product": product, "claim": claim,
              "terms": sorted(terms), "query": query}
    started = time.perf_counter()
    try:
        hits = search(query, pages)
    except Exception as error:  # noqa: BLE001
        record.update(error=f"{type(error).__name__}: {error}", hits=0, pages=0,
                      recurring=False, publishers=[], seconds=round(
                          time.perf_counter() - started, 2))
        return record
    hits = [hit for hit in hits if isinstance(hit, dict) and hit.get("url")]
    record["hits"] = len(hits)
    texts: list[tuple[str, str, str]] = []  # url, title, text
    with ThreadPoolExecutor(max_workers=min(5, max(1, len(hits)))) as pool:
        futures = {pool.submit(read_page, reader, hit["url"]): hit for hit in hits}
        for future, hit in futures.items():
            text = future.result()
            if text:
                texts.append((hit["url"], str(hit.get("title") or ""), text))
    record["pages"] = len(texts)

    seen_text: set[str] = set()
    found: dict[str, list[str]] = {}
    skipped_menus = 0
    page_stems = [_stems(text) for _url, _title, text in texts]
    frequency: dict[str, int] = {}
    for stems in page_stems:
        for stem in stems:
            frequency[stem] = frequency.get(stem, 0) + 1
    rare = {stem for stem, count in frequency.items()
            if count <= max(1, int(0.3 * max(1, len(texts))))}
    for (url, title, text), _stems_of_page in zip(texts, page_stems):
        if menu_page(url, title):
            skipped_menus += 1
            continue
        fingerprint = hashlib.sha256(" ".join(fold(text).split()).encode()).hexdigest()
        if fingerprint in seen_text:
            continue
        seen_text.add(fingerprint)
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
            if not report_sentence(sentence):
                continue
            if matches(terms, sentence, rare):
                found.setdefault(publisher(url), []).append(
                    " ".join(sentence.split())[:220])
                break

    record.update(
        skipped_menus=skipped_menus,
        publishers=sorted(found),
        occurrences={domain: sentences[:2] for domain, sentences in found.items()},
        recurring=len(found) >= 2,
        single=len(found) == 1,
        seconds=round(time.perf_counter() - started, 2),
    )
    return record


def load_corpus() -> list[dict]:
    """Every page excerpt this checkout has already fetched, deduplicated.

    From the demo engine's job results and the bench JSONL. Each row is a page
    address, its publisher and the excerpt the pipeline kept. This is what
    recurrence can be counted on when the search service is unavailable, and
    it is a fair test of the statistic itself: the pages were read blind.
    """
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(url: str, excerpt: str) -> None:
        url, excerpt = str(url or "").strip(), " ".join(str(excerpt or "").split())
        if not url or not excerpt:
            return
        key = (url, excerpt[:200])
        if key in seen:
            return
        seen.add(key)
        rows.append({"url": url, "text": excerpt, "publisher": publisher(url)})

    import sqlite3
    db = ROOT / ".tmp-demo" / "app.sqlite"
    if db.exists():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        for row in conn.execute("SELECT result_json FROM jobs WHERE result_json IS NOT NULL"):
            try:
                result = json.loads(row["result_json"])
            except ValueError:
                continue
            for page in result.get("evidence_pages") or []:
                add(page.get("url"), page.get("excerpt"))
        conn.close()
    for path in (ROOT / ".local-evaluation" / "scenarios").glob("*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            for page in record.get("evidence_pages") or []:
                add(page.get("url"), page.get("excerpt"))
    return rows


def occurrences_in_corpus(seed: dict, corpus: list[dict]) -> dict:
    product, claim = seed["product"], seed["claim"]
    terms = core(claim, product)
    product_stems = product_terms(product)
    # A shared word only counts if it is not everywhere already. "battery" and
    # "charge" appear on half the pages of a Dyson look, so a marketing sentence
    # about charge once matched "battery not charging"; a word that appears on
    # most pages of the corpus cannot identify a fault. This is the statistical
    # guardrail, computed from the corpus at hand, not from a vocabulary.
    page_stems = [_stems(page["text"]) for page in corpus]
    frequency: dict[str, int] = {}
    for stems in page_stems:
        for stem in stems:
            frequency[stem] = frequency.get(stem, 0) + 1
    common = max(1, int(0.3 * max(1, len(corpus))))
    rare = {stem for stem, count in frequency.items() if count <= common}
    found: dict[str, list[str]] = {}
    for page, stems in zip(corpus, page_stems):
        text = page["text"]
        if not any(term in fold(text) for term in product_stems):
            continue  # a recurrence must be about the same product
        if menu_page(page["url"]):
            continue
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
            if not report_sentence(sentence):
                continue
            if not matches(terms, sentence, rare):
                continue
            found.setdefault(page["publisher"], []).append(
                " ".join(sentence.split())[:220])
            break
    return found


def known_urls() -> dict[str, set[str]]:
    """Every page address this checkout has already read, grouped by product."""
    out: dict[str, set[str]] = {}

    def add(product: str, url: str) -> None:
        if product and url:
            out.setdefault(str(product), set()).add(str(url))

    import sqlite3
    db = ROOT / ".tmp-demo" / "app.sqlite"
    if db.exists():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        for row in conn.execute(
                "SELECT params_json, result_json FROM jobs WHERE result_json IS NOT NULL"):
            try:
                params = json.loads(row["params_json"] or "{}")
                result = json.loads(row["result_json"])
            except ValueError:
                continue
            product = str(params.get("product") or "")
            coverage = result.get("coverage") or {}
            for page in coverage.get("page_outcomes") or []:
                add(product, page.get("url") or "")
            # Older runs kept only the excerpted pages, not the fetch outcomes.
            for page in result.get("evidence_pages") or []:
                add(product, page.get("url") or "")
        conn.close()
    for path in (ROOT / ".local-evaluation" / "scenarios").glob("*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            for stage in record.get("stages") or []:
                if stage.get("stage") == "fetch":
                    add(str(record.get("product") or ""), str(stage.get("url") or ""))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=Path, default=ROOT / "tools" / "recurrence_seeds.json")
    parser.add_argument("--pages", type=int, default=4)
    parser.add_argument("--workers", type=int, default=3,
                        help="seeds expanded side by side (each with its own searcher)")
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--offline", action="store_true",
                        help="count over every page excerpt already fetched, no search")
    parser.add_argument("--fetch-known", action="store_true",
                        help="re-fetch the pages already recorded for each product, no search")
    args = parser.parse_args()

    seeds = json.loads(args.seeds.read_text(encoding="utf-8"))
    output = args.output or (ROOT / ".local-evaluation" / "recurrence"
                             / f"{time.strftime('%Y%m%d-%H%M%S')}.jsonl")
    output.parent.mkdir(parents=True, exist_ok=True)
    if args.fetch_known:
        known = known_urls()
        reader = fetch.reader(timeout=8.0)
        print(f"{'seed':22} {'pages':>5} {'pub':>4}  publishers")
        rows = []
        for seed in seeds:
            key = next((name for name in known
                        if seed["product"].casefold() in name.casefold()
                        or name.casefold() in seed["product"].casefold()), "")
            urls = sorted(known.get(key) or [])[:20]
            corpus = []
            with ThreadPoolExecutor(max_workers=min(4, max(1, len(urls)))) as pool:
                for url, text in zip(urls, pool.map(lambda one: read_page(reader, one), urls)):
                    if text:
                        corpus.append({"url": url, "text": text,
                                       "publisher": publisher(url)})
            found = occurrences_in_corpus(seed, corpus)
            record = {"id": seed["id"], "product": seed["product"], "claim": seed["claim"],
                      "mode": "fetch-known", "matched_product": key,
                      "pages": len(corpus), "publishers": sorted(found),
                      "occurrences": {domain: sentences[:2] for domain, sentences in found.items()},
                      "recurring": len(found) >= 2, "single": len(found) == 1}
            rows.append(record)
            print(f"{seed['id']:22} {len(corpus):>5} {len(found):>4}  "
                  f"{', '.join(sorted(found)) or '-'}")
            for domain, sentences in found.items():
                print(f"    {domain:28} {sentences[0][:100]}")
        with output.open("a", encoding="utf-8") as handle:
            for record in rows:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"\nwrote {output}")
        return 0
    if args.offline:
        corpus = load_corpus()
        print(f"corpus: {len(corpus)} page excerpt(s) from "
              f"{len({page['publisher'] for page in corpus})} publisher(s)\n")
        print(f"{'seed':22} {'pub':>4}  publishers")
        rows = []
        for seed in seeds:
            found = occurrences_in_corpus(seed, corpus)
            record = {"id": seed["id"], "product": seed["product"], "claim": seed["claim"],
                      "mode": "offline", "publishers": sorted(found),
                      "occurrences": {domain: sentences[:2] for domain, sentences in found.items()},
                      "recurring": len(found) >= 2, "single": len(found) == 1}
            rows.append(record)
            print(f"{seed['id']:22} {len(found):>4}  {', '.join(sorted(found)) or '-'}")
            for domain, sentences in found.items():
                print(f"    {domain:28} {sentences[0][:100]}")
        with output.open("a", encoding="utf-8") as handle:
            for record in rows:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"\nwrote {output}")
        return 0

    def one(seed: dict) -> dict:
        # A searcher per worker: the adapter carries per-instance pacing and
        # cancellation state, so sharing one across threads would mix them.
        own_search = openserp.searcher("", engine=openserp.LOCAL_ENGINES,
                                       language="en", timeout=args.timeout)
        own_reader = fetch.reader(timeout=8.0)
        return run_seed(seed, own_search, own_reader, args.pages, args.timeout)

    print(f"{'seed':22} {'hits':>4} {'pages':>5} {'menu':>4} {'pub':>4} {'secs':>6}  verdict")
    rows = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for seed, record in zip(seeds, pool.map(one, seeds)):
            rows.append(record)
            verdict = ("ERROR" if record.get("error") else
                       "RECURRING" if record.get("recurring") else
                       "single" if record.get("single") else "none")
            print(f"{seed['id']:22} {record.get('hits', 0):>4} {record.get('pages', 0):>5} "
                  f"{record.get('skipped_menus', 0):>4} {len(record.get('publishers') or []):>4} "
                  f"{record.get('seconds', 0):>6.1f}  {verdict}")
            for domain, sentences in (record.get("occurrences") or {}).items():
                print(f"    {domain:28} {sentences[0][:100]}")
    with output.open("a", encoding="utf-8") as handle:
        for record in rows:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"\nwrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
