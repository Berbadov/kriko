"""Tier 1 statistics and Tier 2 lightweight scoring for claim recurrence.

Nothing in here knows what a fault is. Tier 1 is arithmetic: how informative a
word is in general English, how alike two sentences are, and how surprising a
count is against a control. Tier 2 is a logistic regression over those same
signals plus, optionally, one static-embedding similarity. It exists only once
there are labelled candidates to fit it on, and it scores in microseconds.

Optional dependencies, each with a fallback:
    wordfreq   word weights        (fallback: every word weighs 1, old rule)
    model2vec  static embeddings   (fallback: similarity feature is 0)
    numpy      training only       (inference is plain Python)

Run the experiment (search, read, decide; no model in the loop unless --model):

    .venv/Scripts/python.exe tools/claim_recurrence.py
    .venv/Scripts/python.exe tools/claim_recurrence.py --limit 5 --pages 3
    .venv/Scripts/python.exe tools/claim_recurrence.py --offline
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

TOKEN = re.compile(r"[^\W_]+")
SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


def tokens(text: str) -> list[str]:
    return TOKEN.findall(text.casefold())


# --- Tier 1: word weights ---------------------------------------------------

try:
    from wordfreq import zipf_frequency as _zipf
except ImportError:  # pragma: no cover - optional
    _zipf = None

WORD_WEIGHTS = _zipf is not None
# Zipf <= 4: rarer than "battery" (4.5) or "charging" (4.2), as rare as "hinge"
# (3.3). A word this common in general English cannot identify a fault alone.
RARE_WEIGHT = 0.5


@lru_cache(maxsize=1 << 16)
def word_weight(word: str) -> float:
    """~0 for 'the', 0.44 for 'battery', 0.87 for 'delaminating', 1 unseen."""
    if _zipf is None:
        return 1.0
    return min(1.0, max(0.05, (8.0 - _zipf(word, "en")) / 8.0))


# Grammar, not a fault vocabulary: these mark a sentence that mentions the
# symptom in order to deny it ("never had any battery issues").
NEGATOR = re.compile(
    r"\b(?:no|not|never|none|nothing|cannot|without|nor|\w+n['\u2019]t|"
    r"cant|wont|dont|doesnt|didnt|isnt|wasnt|wouldnt|couldnt|havent)\b", re.I)
CONTRAST = re.compile(
    r"\b(?:no|never|zero|without|not\s+(?:a|any|one))\s+(?:\w+\s+){0,2}?"
    r"(?:issues?|problems?|complaints?|trouble|faults?)\b"
    r"|\bnever\s+(?:had|experienced|noticed|seen)\b"
    r"|\b(?:did\s*n[o'\u2019]?t|have\s*n[o'\u2019]?t|has\s*n[o'\u2019]?t)\s+"
    r"(?:had|have|experienced?|noticed?|seen|see)\b"
    r"|\bunlike\b", re.I)


def negations(text: str) -> int:
    return len(NEGATOR.findall(text))


@dataclass
class Claim:
    text: str
    stems: dict[str, float]  # content stem -> weight
    negated: bool


def make_claim(text: str, product: str, stems_fn: Callable[[str], set[str]]) -> Claim:
    """The claim's content stems without the product's, each weighted by the
    rarest surface word that produced it."""
    allowed = stems_fn(text) - stems_fn(product)
    weights: dict[str, float] = {}
    for word in tokens(text):
        for stem in stems_fn(word) & allowed:
            weights[stem] = max(weights.get(stem, 0.0), word_weight(word))
    for stem in allowed - weights.keys():
        weights[stem] = 1.0  # produced only by a phrase; treat as specific
    return Claim(text, weights, negations(text) > 0)


# --- Tier 1: independence ---------------------------------------------------

DUPLICATE = 0.6  # Jaccard of 5-character shingles; syndicated copies sit ~0.9


def shingles(text: str, size: int = 5) -> set[str]:
    flat = " ".join(text.casefold().split())
    return {flat[i:i + size] for i in range(max(1, len(flat) - size + 1))}


def independent_sources(matches: dict[str, str]) -> list[list[str]]:
    """Publishers grouped so that near-copies of one sentence are one source.

    Exact Jaccard is affordable here: it runs on the matched sentences of one
    seed (tens at most), not on the corpus. MinHash only pays at corpus scale.
    """
    groups: list[tuple[set[str], list[str]]] = []
    for name, sentence in sorted(matches.items()):
        own = shingles(sentence)
        for shared, members in groups:
            union = own | shared
            if union and len(own & shared) / len(union) >= DUPLICATE:
                members.append(name)
                break
        else:
            groups.append((own, [name]))
    return [members for _shared, members in groups]


# --- Tier 1: the count against a control ------------------------------------

def prob_above_control(k: int, n: int, k0: int, n0: int,
                       samples: int = 4000, seed: int = 0) -> float:
    """P(rate of the claim > rate of the controls), Beta(1, 1) priors.

    k of n independent publishers carry the claim; k0 of n0 publisher trials
    carry a control. Monte Carlo is a few milliseconds and needs no SciPy.
    """
    if n <= 0:
        return 0.0
    rng = random.Random(seed)
    a, b = (k + 1, n - k + 1), (k0 + 1, n0 - k0 + 1)
    return sum(rng.betavariate(*a) > rng.betavariate(*b)
               for _ in range(samples)) / samples


# --- Signals ---------------------------------------------------------------

FEATURES = ("containment", "shared", "rare_shared", "negation_mismatch",
            "contrast", "product_distance", "log_length", "window", "embedding")
DISTANCE_CAP = 20


def features(claim: Claim, sentence: str, sentence_stems: set[str],
             distance: int, window: bool, similarity: float) -> dict[str, float]:
    shared = claim.stems.keys() & sentence_stems
    total = sum(claim.stems.values()) or 1.0
    return {
        "containment": sum(claim.stems[stem] for stem in shared) / total,
        "shared": float(len(shared)),
        "rare_shared": float(sum(claim.stems[stem] >= RARE_WEIGHT for stem in shared)),
        "negation_mismatch": float((negations(sentence) > 0) != claim.negated),
        "contrast": float(bool(CONTRAST.search(sentence))),
        "product_distance": min(distance, DISTANCE_CAP) / DISTANCE_CAP,
        "log_length": math.log(max(len(sentence), 1) / 100),
        "window": float(window),
        "embedding": float(similarity),
    }


def rule(f: dict[str, float], claim_size: int) -> bool:
    """Tier 1: the three-stem rule, weighted and guarded.

    Three shared stems still; half the claim's *weight* instead of half its
    count; at least one shared word that is rare in English (the guardrail the
    old `rare` argument promised and never applied); no contrast phrase. Two
    joined sentences must cover more, since a longer text covers more by
    chance.
    """
    if claim_size < 3:
        return False
    need = 0.6 if f["window"] else 0.5
    return (f["shared"] >= 3 and f["containment"] >= need
            and (f["rare_shared"] >= 1 or not WORD_WEIGHTS)
            and not f["contrast"])


# --- Tier 2: static embeddings ----------------------------------------------

DEFAULT_EMBEDDING = "minishlab/potion-base-8M"


class Embedder:
    """Model2Vec static embeddings: a lookup and a mean, no transformer."""

    def __init__(self, name: str = DEFAULT_EMBEDDING, enabled: bool = True):
        self.name, self.model, self.error = name, None, ""
        self._cache: dict[str, list[float]] = {}
        if not enabled:
            self.error = "disabled"
            return
        try:
            from model2vec import StaticModel
            self.model = StaticModel.from_pretrained(name)
        except Exception as error:  # noqa: BLE001 - optional dependency
            self.error = f"{type(error).__name__}: {error}"

    @property
    def available(self) -> bool:
        return self.model is not None

    def _units(self, texts: list[str]) -> list[list[float]]:
        missing = [text for text in dict.fromkeys(texts) if text not in self._cache]
        if missing:
            for text, vector in zip(missing, self.model.encode(missing)):
                norm = math.sqrt(float((vector * vector).sum())) or 1.0
                self._cache[text] = (vector / norm).tolist()
        return [self._cache[text] for text in texts]

    def similarities(self, claim: str, texts: list[str]) -> list[float]:
        """Cosine of each text to the claim; sentences are cached, so control
        claims scored on the same pages cost one encode, not four."""
        if not self.available or not texts:
            return [0.0] * len(texts)
        units = self._units([claim, *texts])
        anchor = units[0]
        return [sum(a * b for a, b in zip(anchor, unit)) for unit in units[1:]]


# --- Tier 2: logistic regression --------------------------------------------

@dataclass
class Model:
    features: list[str]
    mean: list[float]
    scale: list[float]
    weights: list[float]
    bias: float
    threshold: float
    embedding: str | None

    def probability(self, f: dict[str, float]) -> float:
        z = self.bias + sum(w * (f.get(name, 0.0) - m) / s for name, w, m, s
                            in zip(self.features, self.weights, self.mean, self.scale))
        return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")


def load_model(path: Path) -> Model:
    return Model(**json.loads(path.read_text(encoding="utf-8")))


def _fit(X, y, l2: float = 1.0, steps: int = 2000, rate: float = 0.5):
    import numpy as np
    mean, scale = X.mean(0), X.std(0)
    scale[scale == 0] = 1.0
    Z = (X - mean) / scale
    pos = y.sum()
    weight = np.where(y == 1, len(y) / (2 * max(pos, 1)), len(y) / (2 * max(len(y) - pos, 1)))
    w, b = np.zeros(Z.shape[1]), 0.0
    for _ in range(steps):
        p = 1 / (1 + np.exp(-(Z @ w + b)))
        g = weight * (p - y)
        w -= rate * (Z.T @ g + l2 * w) / len(y)
        b -= rate * g.mean()
    return w, b, mean, scale


def _predict(X, w, b, mean, scale):
    import numpy as np
    return 1 / (1 + np.exp(-(((X - mean) / scale) @ w + b)))


def train(rows: list[dict], embedding: str = DEFAULT_EMBEDDING,
          folds: int = 5, seed: int = 0) -> tuple[Model, dict]:
    """Fit on labelled candidates; pick the threshold on out-of-fold scores.

    Folds are split by page address, so the two halves of a joined sentence
    and the rest of the same page never sit on both sides of a fold.
    """
    import numpy as np
    labels = [int(row["label"]) for row in rows]
    if len(rows) < 20 or len(set(labels)) < 2:
        raise ValueError("need at least 20 labelled candidates, with both labels")
    use_embedding = any(abs(row["features"].get("embedding", 0.0)) > 1e-9 for row in rows)
    names = [name for name in FEATURES if use_embedding or name != "embedding"]
    X = np.array([[float(row["features"].get(name, 0.0)) for name in names] for row in rows])
    y = np.array(labels, dtype=float)

    urls = sorted({str(row.get("url", i)) for i, row in enumerate(rows)})
    if len(urls) < 3:
        raise ValueError(f"need at least 3 distinct pages to fold by page, got {len(urls)}")
    random.Random(seed).shuffle(urls)
    k = max(2, min(folds, len(urls)))
    fold_of = {url: i % k for i, url in enumerate(urls)}
    fold = np.array([fold_of[str(row.get("url", i))] for i, row in enumerate(rows)])
    oof = np.zeros(len(y))
    predicted = np.zeros(len(y), dtype=bool)
    fitted = 0
    for f in range(k):
        test, fit_on = fold == f, fold != f
        if not test.any() or len(set(y[fit_on])) < 2:
            continue
        oof[test] = _predict(X[test], *_fit(X[fit_on], y[fit_on]))
        predicted[test] = True
        fitted += 1
    if fitted < 2:
        raise ValueError("no usable folds: labels are not spread across pages")

    # Score only the rows a model actually saw out of fold; a skipped fold left
    # zeros there, and counting those as confident negatives understates it.
    scored, truth = oof[predicted], y[predicted]

    def scores(threshold: float) -> tuple[float, float, float]:
        guess = scored >= threshold
        tp = float((guess & (truth == 1)).sum())
        precision = tp / max(guess.sum(), 1)
        recall = tp / max((truth == 1).sum(), 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-9)
        return precision, recall, f1

    # Among the thresholds that tie on F1, the highest: on separable data every
    # threshold between the classes scores 1.0, and taking the first (0.05)
    # leaves the model accepting almost any candidate later.
    grid = [t / 100 for t in range(5, 96)]
    best = max(scores(t)[2] for t in grid)
    threshold = max(t for t in grid if scores(t)[2] >= best - 1e-12)
    precision, recall, f1 = scores(threshold)
    w, b, mean, scale = _fit(X, y)
    model = Model(names, mean.tolist(), scale.tolist(), w.tolist(), float(b),
                  threshold, embedding if use_embedding else None)
    report = {
        "candidates": len(rows), "positives": int(y.sum()), "folds": fitted,
        "threshold": threshold, "cv_precision": round(float(precision), 3),
        "cv_recall": round(float(recall), 3), "cv_f1": round(float(f1), 3),
        "embedding": model.embedding,
        "weights": {name: round(float(v), 3) for name, v in zip(names, w)},
    }
    return model, report


class Scorer:
    """The model when there is one it can run, otherwise the Tier 1 rule."""

    def __init__(self, model: Model | None, embedder_available: bool):
        self.model, self.note = None, "tier 1 rule"
        if model and model.embedding and not embedder_available:
            self.note = "tier 1 rule (model needs embeddings, none loaded)"
        elif model:
            self.model = model
            self.note = f"tier 2 model (threshold {model.threshold:.2f})"

    def decide(self, f: dict[str, float], claim_size: int) -> tuple[bool, float]:
        """A contrast phrase is a veto in both tiers: a sentence that denies the
        symptom is never a report of it, however many words it shares, and a
        few hundred labels should not be able to outvote grammar."""
        if f["contrast"]:
            return False, 0.0
        if self.model:
            p = self.model.probability(f)
            return claim_size >= 2 and p >= self.model.threshold, p
        return rule(f, claim_size), f["containment"]


# --- The experiment: search, read, decide -----------------------------------

from app.providers import fetch, openserp  # noqa: E402
from app.providers.local_identity import fold  # noqa: E402
from app.providers.local_pipeline import _FILLER, menu_page, publisher  # noqa: E402

MIN_SENTENCE = 40
SNIPPET = 220
STEM_LENGTH = 6
LETTERS = re.compile(r"[^\W\d_]{4,}")


def stems(text: str) -> set[str]:
    """Content stems at six characters.

    Five conflate words that are not the same: `disconnect` and `discoverable`
    both became `disco`, which let a pair of pairing instructions count as a
    report of disconnects. Six keeps `discon` and `discov` apart and still
    joins the inflections that are the same word.
    """
    return {word[:STEM_LENGTH] for word in LETTERS.findall(text.casefold())
            if word not in _FILLER}


def report_sentence(sentence: str) -> bool:
    """A sentence that could be a report: not a heading, not a question."""
    text = " ".join(sentence.split())
    return len(text) >= MIN_SENTENCE and "?" not in text


def product_terms(product: str) -> set[str]:
    """The words that make this product itself, not its brand.

    A code (`V11`, `WH-1000XM4`, `T480`) is decisive; without one, the longest
    words. The brand alone is not enough: a recurrence counted on "Sony" once
    matched a WH-1000XM3 article to a WH-1000XM4 seed.
    """
    tokens = {token.casefold() for token in TOKEN.findall(product)}
    codes = {token for token in tokens
             if any(char.isdigit() for char in token) or len(token) >= 6}
    return codes or {token for token in tokens if len(token) >= 4}


def read_page(reader, url: str) -> str:
    try:
        got = reader(url)
        return str(getattr(got, "text", got) or "").strip()
    except Exception:  # noqa: BLE001 - a fetch is a network boundary
        return ""


def page_sentences(text: str) -> list[str]:
    return [" ".join(part.split()) for part in SPLIT.split(text)
            if report_sentence(part)]


def product_mentions(sentences: list[str], terms: set[str]) -> list[int]:
    return [index for index, sentence in enumerate(sentences)
            if any(term in fold(sentence) for term in terms)]


def names_product(text: str, terms: set[str]) -> bool:
    """Whether the page names the product at all.

    Asked of the whole text, not of the reportable sentences: a page can carry
    the model number on a short line ("Model: WH-1000XM4") that is too short to
    be a report, and that page is still about this product.
    """
    folded = fold(text)
    return any(term in folded for term in terms)


def count_publishers(found: dict[str, list[tuple[str, float]]]) -> list[list[str]]:
    """One matched sentence per publisher, near-copies counted once."""
    first = {domain: sentences[0][0] for domain, sentences in found.items()}
    return independent_sources(first)


# --- Tier 1: threads, not only publishers -----------------------------------
#
# Two independent publishers is the honest bar and the rare one: a fault on one
# forum thread and one support article is already a good answer. Count a second
# unit instead, the thread, but only where the URL is a discussion: three
# separate threads on one forum are three people, while three articles on one
# review site are one editor.
#
# This is address structure, not site data: no host appears here.

DISCUSSION_PATH = re.compile(
    r"/(?:threads?|topics?|discussions?|forums?|questions?|answers?|comments?|"
    r"community|viewtopic|showthread|t\d*)(?:/|$|\.php)", re.I)
DISCUSSION_QUERY = re.compile(r"[?&](?:t|tid|thread|threadid|topic|topicid)=", re.I)
PAGING = re.compile(r"/(?:page|p)/\d+$", re.I)
PAGING_PARAMS = {"page", "paged", "pg", "pagenum", "start", "offset"}
THREAD_PARAMS = {"t", "tid", "thread", "threadid", "topic", "topicid"}
MIN_PUBLISHERS = 2
MIN_THREADS = 3


def thread_of(url: str) -> str:
    """The page a match sits on, without its pagination.

    A discussion usually keeps its thread in the path (`/threads/12345`), so
    the query is dropped there; a bare script keeps it in the query
    (`viewtopic.php?t=99`) and only the thread parameters survive. A page that
    is not a discussion keeps its query without paging, so two blog posts
    (`?p=77`) do not collapse into one.
    """
    parts = urlsplit(url)
    path = PAGING.sub("", parts.path.rstrip("/")) or "/"
    host = (parts.hostname or "").lower()
    pairs = [pair for pair in parts.query.split("&") if pair]
    if DISCUSSION_PATH.search(path):
        kept = [pair for pair in pairs
                if pair.split("=")[0].lower() in THREAD_PARAMS]
        query = "&".join(sorted(kept))
        return f"{host}{path}" + (f"?{query}" if query else "")
    kept = [pair for pair in pairs
            if pair.split("=")[0].lower() not in PAGING_PARAMS]
    query = "&".join(sorted(kept))
    return f"{host}{path}" + (f"?{query}" if query else "")


def is_discussion(url: str) -> bool:
    parts = urlsplit(url)
    return bool(DISCUSSION_PATH.search(parts.path)
                or DISCUSSION_QUERY.search(f"?{parts.query}"))


def discussion_threads(urls: list[str]) -> list[str]:
    return sorted({thread_of(url) for url in urls if is_discussion(url)})


def occurrences(found: dict[str, list[tuple[str, float]]]) -> dict[str, list[str]]:
    return {domain: [sentence[:SNIPPET] for sentence, _score in sentences[:2]]
            for domain, sentences in found.items()}


@dataclass
class Match:
    sentence: str
    score: float
    window: bool


def judge_page(scorer: Scorer, claim: Claim, text: str, terms: set[str],
               embedder: Embedder | None, window: bool = False) -> tuple[Match | None, int]:
    """The first sentence on this page a scorer would count, and how many were tried.

    Single sentences come first; only when none matches are two joined, and the
    rule asks a joined pair to cover more of the claim, because a longer text
    covers more by chance. The page must name the product: a claim repeated
    about the same *kind* of thing is not a recurrence about this one.
    """
    if not names_product(text, terms):
        return None, 0
    sentences = page_sentences(text)
    near = product_mentions(sentences, terms)
    units: list[tuple[str, bool, int]] = [(s, False, index)
                                          for index, s in enumerate(sentences)]
    if window:
        units += [(" ".join(sentences[index:index + 2]), True, index)
                  for index in range(len(sentences) - 1)]
    for joined, paired, index in units:
        distance = (min(abs(index - at) for at in near) if near
                    else DISTANCE_CAP)
        if paired and near:
            distance = min(distance, min(abs(index + 1 - at) for at in near))
        similarity = (embedder.similarities(claim.text, [joined])[0]
                      if embedder and embedder.available else 0.0)
        f = features(claim, joined, stems(joined), distance, paired, similarity)
        keep, score = scorer.decide(f, len(claim.stems))
        if keep:
            return Match(joined, score, paired), len(sentences)
    return None, len(sentences)


def run_seed(seed: dict, search, reader, pages: int, scorer: Scorer,
             embedder: Embedder | None, window: bool = False) -> dict:
    product, claim_text = seed["product"], seed["claim"]
    claim = make_claim(claim_text, product, stems)
    terms = product_terms(product)
    query = f'"{product}" {claim_text}'[:240]
    record = {"id": seed["id"], "product": product, "claim": claim_text,
              "terms": sorted(claim.stems), "query": query, "scorer": scorer.note,
              "window": window, "stem_length": STEM_LENGTH}
    started = time.perf_counter()
    try:
        hits = search(query, pages)
    except Exception as error:  # noqa: BLE001 - a search is a network boundary
        record.update(error=f"{type(error).__name__}: {error}", hits=0, pages=0,
                      recurring=False, publishers=[], sources=[], threads=[],
                      seconds=round(time.perf_counter() - started, 2))
        return record
    hits = [hit for hit in hits if isinstance(hit, dict) and hit.get("url")]
    record["hits"] = len(hits)
    with ThreadPoolExecutor(max_workers=min(5, max(1, len(hits)))) as pool:
        texts = list(pool.map(lambda hit: read_page(reader, hit["url"]), hits))
    pages_read = [(hit["url"], str(hit.get("title") or ""), text)
                  for hit, text in zip(hits, texts) if text]
    record["pages"] = len(pages_read)

    seen: set[str] = set()
    found: dict[str, list[tuple[str, float]]] = {}
    matched: list[str] = []
    outcomes: list[dict] = []
    for url, title, text in pages_read:
        outcome = {"url": url, "publisher": publisher(url)}
        fingerprint = hashlib.sha256(" ".join(fold(text).split()).encode()).hexdigest()
        if fingerprint in seen:
            outcome["verdict"] = "duplicate"
        elif menu_page(url, title):
            outcome["verdict"] = "menu"
        elif not names_product(text, terms):
            outcome["verdict"] = "off_product"
        else:
            match, tried = judge_page(scorer, claim, text, terms, embedder, window)
            outcome["sentences"] = tried
            if match is None:
                outcome["verdict"] = "no_match"
            else:
                outcome.update(verdict="matched", score=round(match.score, 3),
                               window=match.window, quote=match.sentence[:SNIPPET])
                found.setdefault(publisher(url), []).append(
                    (match.sentence, match.score))
                matched.append(url)
        seen.add(fingerprint)
        outcomes.append(outcome)

    record.update(summarise(found, matched, outcomes),
                  seconds=round(time.perf_counter() - started, 2))
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


def summarise(found: dict[str, list[tuple[str, float]]], matched: list[str],
              outcomes: list[dict]) -> dict:
    """Everything one seed's pages settle: sources, threads, and why pages fell."""
    sources = count_publishers(found)
    threads = discussion_threads(matched)
    verdicts = [one["verdict"] for one in outcomes]
    return {
        "skipped_menus": verdicts.count("menu"),
        "skipped_offproduct": verdicts.count("off_product"),
        "skipped_duplicates": verdicts.count("duplicate"),
        "pages_judged": sum(1 for verdict in verdicts if verdict != "duplicate"),
        "publishers": sorted(found), "sources": sources, "threads": threads,
        "occurrences": occurrences(found), "page_outcomes": outcomes,
        "recurring": (len(sources) >= MIN_PUBLISHERS
                      or len(threads) >= MIN_THREADS),
        "single": len(sources) == 1,
    }


def judge_corpus(seed: dict, corpus: list[dict], scorer: Scorer,
                 embedder: Embedder | None, window: bool = False) -> tuple[dict, list[str], list[dict]]:
    product, claim_text = seed["product"], seed["claim"]
    claim = make_claim(claim_text, product, stems)
    terms = product_terms(product)
    found: dict[str, list[tuple[str, float]]] = {}
    matched: list[str] = []
    outcomes: list[dict] = []
    seen: set[str] = set()
    for page in corpus:
        outcome = {"url": page["url"], "publisher": page["publisher"]}
        fingerprint = hashlib.sha256(
            " ".join(fold(page["text"]).split()).encode()).hexdigest()
        if fingerprint in seen:
            outcome["verdict"] = "duplicate"
        elif menu_page(page["url"]):
            outcome["verdict"] = "menu"
        elif not names_product(page["text"], terms):
            outcome["verdict"] = "off_product"
        else:
            match, tried = judge_page(scorer, claim, page["text"], terms,
                                      embedder, window)
            outcome["sentences"] = tried
            if match is None:
                outcome["verdict"] = "no_match"
            else:
                outcome.update(verdict="matched", score=round(match.score, 3),
                               window=match.window, quote=match.sentence[:SNIPPET])
                found.setdefault(page["publisher"], []).append(
                    (match.sentence, match.score))
                matched.append(page["url"])
        seen.add(fingerprint)
        outcomes.append(outcome)
    return found, matched, outcomes


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


def print_seed(seed: dict, record: dict) -> None:
    verdict = ("ERROR" if record.get("error") else
               "RECURRING" if record.get("recurring") else
               "single" if record.get("single") else "none")
    print(f"{seed['id']:24} {len(record.get('sources') or []):>2} source(s) "
          f"{len(record.get('threads') or []):>2} thread(s)  {verdict}")
    for domain, sentences in (record.get("occurrences") or {}).items():
        print(f"    {domain:28} {sentences[0][:100]}")


def evaluate(rows: list[dict]) -> dict:
    """What the seed set settled: faults found, headings kept, and recurrence.

    The seed id says which class it is, so the tool can report a rate instead
    of a vibe. `found` means at least one page matched; `recurring` is the
    threshold verdict.
    """
    def count(prefix: str) -> tuple[int, int, int]:
        group = [row for row in rows if str(row.get("id", "")).startswith(prefix)]
        found = sum(bool(row.get("sources")) for row in group)
        recurring = sum(bool(row.get("recurring")) for row in group)
        return len(group), found, recurring

    total_true, true_found, true_recurring = count("true-")
    total_false, false_found, false_recurring = count("false-")
    return {"true": total_true, "true_found": true_found,
            "true_recurring": true_recurring,
            "false": total_false, "false_kept": false_found,
            "false_recurring": false_recurring}


def print_evaluation(rows: list[dict]) -> None:
    report = evaluate(rows)
    print(f"\ntrue: {report['true_found']}/{report['true']} found, "
          f"{report['true_recurring']}/{report['true']} recurring  ·  "
          f"false: {report['false_kept']}/{report['false']} kept, "
          f"{report['false_recurring']}/{report['false']} recurring")


def scorer_for(args) -> tuple[Scorer, Embedder | None]:
    model = load_model(args.model) if args.model else None
    embedder = Embedder(enabled=not args.no_embedding)
    if embedder.error and embedder.error != "disabled":
        print(f"embeddings unavailable ({embedder.error}); scoring without them")
    return Scorer(model, embedder.available), embedder


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=Path, default=ROOT / "tools" / "recurrence_seeds.json")
    parser.add_argument("--limit", type=int, default=0, help="first N seeds only")
    parser.add_argument("--pages", type=int, default=4)
    parser.add_argument("--workers", type=int, default=3,
                        help="seeds expanded side by side (each with its own searcher)")
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--model", type=Path, default=None,
                        help="a fitted Tier 2 model (JSON); default is the Tier 1 rule")
    parser.add_argument("--no-embedding", action="store_true",
                        help="do not try to load static embeddings")
    parser.add_argument("--window", action="store_true",
                        help="also try two joined sentences (measured: adds a false source, not a true one)")
    parser.add_argument("--offline", action="store_true",
                        help="count over every page excerpt already fetched, no search")
    parser.add_argument("--fetch-known", action="store_true",
                        help="re-fetch the pages already recorded for each product, no search")
    args = parser.parse_args()

    seeds = json.loads(args.seeds.read_text(encoding="utf-8"))
    if args.limit:
        seeds = seeds[:args.limit]
    output = args.output or (ROOT / ".local-evaluation" / "recurrence"
                             / f"{time.strftime('%Y%m%d-%H%M%S')}.jsonl")
    output.parent.mkdir(parents=True, exist_ok=True)
    scorer, embedder = scorer_for(args)
    window = args.window
    weights = "wordfreq" if WORD_WEIGHTS else "uniform (wordfreq absent: no rarity guard)"
    print(f"scorer: {scorer.note}; weights: {weights}; "
          f"embeddings: {'on' if embedder and embedder.available else 'off'}; "
          f"window: {'on' if window else 'off'}\n")

    if args.fetch_known:
        known = known_urls()
        reader = fetch.reader(timeout=8.0)
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
            found, matched, outcomes = judge_corpus(seed, corpus, scorer, embedder, window)
            record = {"id": seed["id"], "product": seed["product"], "claim": seed["claim"],
                      "mode": "fetch-known", "matched_product": key,
                      "window": window, "stem_length": STEM_LENGTH,
                      "scorer": scorer.note, "pages": len(corpus), **summarise(
                          found, matched, outcomes)}
            rows.append(record)
            print(f"{seed['id']:24} {len(corpus):>3} page(s)  "
                  f"{len(record['sources'])} source(s)  {len(record['threads'])} thread(s)")
            for domain, sentences in record["occurrences"].items():
                print(f"    {domain:28} {sentences[0][:100]}")
        print_evaluation(rows)
        with output.open("a", encoding="utf-8") as handle:
            for record in rows:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"\nwrote {output}")
        return 0

    if args.offline:
        corpus = load_corpus()
        print(f"corpus: {len(corpus)} page excerpt(s) from "
              f"{len({page['publisher'] for page in corpus})} publisher(s)\n")
        rows = []
        for seed in seeds:
            found, matched, outcomes = judge_corpus(seed, corpus, scorer, embedder, window)
            record = {"id": seed["id"], "product": seed["product"], "claim": seed["claim"],
                      "mode": "offline", "scorer": scorer.note,
                      "window": window, "stem_length": STEM_LENGTH,
                      **summarise(found, matched, outcomes)}
            rows.append(record)
            print_seed(seed, record)
        print_evaluation(rows)
        with output.open("a", encoding="utf-8") as handle:
            for record in rows:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"\nwrote {output}")
        return 0

    def one(seed: dict) -> dict:
        # A searcher per worker: the adapter carries per-instance pacing and
        # cancellation state, so sharing one across threads would mix them.
        # A resubmitted search gets a new one; the old searcher's budget was
        # what ran out, so retrying on it would fail the same way.
        attempts = 0
        record: dict = {}
        while attempts < 2:
            attempts += 1
            own_search = openserp.searcher("", engine=openserp.LOCAL_ENGINES,
                                           language="en", timeout=args.timeout)
            record = run_seed(seed, own_search, fetch.reader(timeout=8.0),
                              args.pages, scorer, embedder, window)
            if not record.get("error"):
                break
        record["attempts"] = attempts
        return record

    print(f"{'seed':24} {'hits':>4} {'pages':>5} {'menu':>4} {'off':>3} {'src':>3} "
          f"{'thr':>3} {'secs':>6}  verdict")
    rows = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        for seed, record in zip(seeds, pool.map(one, seeds)):
            rows.append(record)
            verdict = ("ERROR" if record.get("error") else
                       "RECURRING" if record.get("recurring") else
                       "single" if record.get("single") else "none")
            print(f"{seed['id']:24} {record.get('hits', 0):>4} {record.get('pages', 0):>5} "
                  f"{record.get('skipped_menus', 0):>4} {record.get('skipped_offproduct', 0):>3} "
                  f"{len(record.get('sources') or []):>3} "
                  f"{len(record.get('threads') or []):>3} "
                  f"{record.get('seconds', 0):>6.1f}  {verdict}")
            for domain, sentences in (record.get("occurrences") or {}).items():
                print(f"    {domain:28} {sentences[0][:100]}")
            if record.get("error"):
                print(f"    {record['error']}")
    print_evaluation(rows)
    with output.open("a", encoding="utf-8") as handle:
        for record in rows:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"\nwrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())