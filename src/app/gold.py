"""Ground truth, as pack data — and what to measure against it.

B126, step one. `app/bench.py` already measures what a run *costs* and what
share of it survived the gate. That is discipline, not correctness: a run
returning two good claims when eight were available scores perfectly, and a
fabricated claim with a real quote in a real page scores as an acceptance.

A **gold set** answers the other half. It ships in the pack —
`research/gold.yaml` — because ground truth for headphones is not ground truth
for cars, and `kriko/` may not know which is which.

**This is not a human in the data path.** The automation principle forbids
per-datum review, and a gold set is not that: it is a one-time authoring
decision like a pack's principle or its search templates, it is versioned with
the pack, and nothing a reader researches ever waits on it. It judges the
*benchmark*, never the knowledge.

The shape, per case:

```yaml
cases:
  - id: buds-pro
    subject_id: <the installed subject this case is about>
    kind: specific          # specific | bulk | validation
    must_find:              # recall — what a competent run produces
      - {claim: "battery degrades in one bud", domain: battery}
    must_not_find:          # precision — plausible and wrong
      - {claim: "bluetooth pairing", why: "true of every wireless earbud"}
    known_absent: ["water damage recall"]   # nothing credible says this
```

Judging is mechanical, cheapest test first, and deliberately *not* an LLM: a
model asked to score another model's output agrees with it far too often, and
the one thing this has to be is independent of the thing it measures.
"""

import re

import yaml

#: Where a pack keeps its gold set. An asset, like the principle and the
#: templates, so it travels with the pack and updates when it does.
ASSET = "research/gold.yaml"

#: Case kinds. `specific` is one subject; `bulk` is an agenda run across many,
#: which is the only way to see quality *degrading with volume* — the failure a
#: single-case benchmark cannot show; `validation` re-checks what is already
#: stored. A closed vocabulary: three different questions, not data that grows.
KINDS = ("specific", "bulk", "validation")


def _flat(text) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip()


def load(conn, pack_id: str) -> list[dict]:
    """The gold cases a pack ships, or `[]`.

    A malformed gold file is an empty list rather than an exception: it can
    only cost a benchmark its ground truth, and a pack that cannot be
    benchmarked must still be usable.
    """
    from kriko.research import pack_asset

    text = pack_asset(conn, pack_id, ASSET)
    if not text.strip():
        return []
    try:
        parsed = yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return []
    cases = parsed.get("cases") if isinstance(parsed, dict) else parsed
    out = []
    for case in cases if isinstance(cases, list) else []:
        if not isinstance(case, dict) or not case.get("subject_id"):
            continue
        out.append({
            "id": str(case.get("id") or case["subject_id"]),
            "pack_id": pack_id,
            "subject_id": str(case["subject_id"]),
            "kind": str(case.get("kind") or "specific"),
            "must_find": [one for one in (case.get("must_find") or [])
                          if isinstance(one, dict)],
            "must_not_find": [one for one in (case.get("must_not_find") or [])
                              if isinstance(one, dict)],
            "known_absent": [str(one) for one in (case.get("known_absent") or [])],
        })
    return out


def all_cases(conn) -> list[dict]:
    """Every installed pack's gold cases, in pack order."""
    packs = [
        row["pack_id"]
        for row in conn.execute(
            "SELECT pack_id FROM packs WHERE enabled = 1 ORDER BY pack_id"
        ).fetchall()
    ]
    return [case for pack_id in packs for case in load(conn, pack_id)]


def matches(entry: dict, title: str, domain: str = "", quote: str = "") -> bool:
    """Does one produced claim answer one gold entry?

    Three tests, cheapest first, and each one is a different kind of evidence:

    1. **domain plus a word** — the pack's own vocabulary, which the gate
       already uses, so a gold entry naming a domain and a component matches a
       claim anchored to both;
    2. **the phrase in the title** — how a gold entry is usually written;
    3. **the phrase in the quote** — for a claim whose title paraphrases what
       its source says.

    Deliberately not exact-match. A gold set written as exact titles would
    measure the agent's wording rather than its findings, and reward it for
    copying a phrase it was never shown.
    """
    wanted = _flat(entry.get("claim") or entry.get("title"))
    if not wanted:
        return False
    domain_wanted = _flat(entry.get("domain"))
    if domain_wanted and _flat(domain) and domain_wanted != _flat(domain):
        return False
    words = [word for word in wanted.split() if len(word) > 3]
    haystacks = (_flat(title), _flat(quote))
    if any(wanted in one for one in haystacks):
        return True
    # Every significant word present, in any order: "battery degrades in one
    # bud" matches "one earbud stops holding charge" only if the gold entry
    # says so, and the author writes the entry knowing that.
    return bool(words) and any(
        all(word in one for word in words) for one in haystacks
    )


def judge(case: dict, produced: list[dict]) -> dict:
    """Score one case's produced claims against its gold entries.

    Four numbers, and the reason they are four rather than one:

    * **found / missed** — recall. A run that stops early scores well on
      everything else and badly here, which is the whole point.
    * **hallucinated** — a claim matching `must_not_find` or `known_absent`.
      Reported apart from precision because the remedies differ: low precision
      is a gate to tighten, hallucination is a plane not to trust unattended.
    * **unlisted** — grounded, and not in the gold set. Counted in its own
      bucket rather than as an error: a gold set is a floor, not a ceiling, and
      penalising a genuinely new find would teach the benchmark to reward
      timidity.
    """
    found, missed = [], []
    for entry in case.get("must_find") or []:
        hit = next(
            (one for one in produced
             if matches(entry, one.get("title", ""), one.get("domain", ""),
                        one.get("quote", ""))),
            None,
        )
        (found if hit else missed).append(
            entry.get("claim") or entry.get("title") or ""
        )

    traps = list(case.get("must_not_find") or []) + [
        {"claim": one} for one in (case.get("known_absent") or [])
    ]
    hallucinated = [
        one.get("title", "")
        for one in produced
        if any(matches(entry, one.get("title", ""), one.get("domain", ""),
                       one.get("quote", "")) for entry in traps)
    ]

    listed = {_flat(one.get("title")) for one in produced
              if any(matches(entry, one.get("title", ""), one.get("domain", ""),
                             one.get("quote", ""))
                     for entry in (case.get("must_find") or []))}
    unlisted = [
        one.get("title", "") for one in produced
        if _flat(one.get("title")) not in listed
        and one.get("title", "") not in hallucinated
    ]

    wanted = len(case.get("must_find") or [])
    produced_count = len(produced)
    return {
        "case": case.get("id", ""),
        "subject_id": case.get("subject_id", ""),
        "kind": case.get("kind", "specific"),
        "found": found,
        "missed": missed,
        "hallucinated": hallucinated,
        "unlisted": unlisted,
        "recall": round(len(found) / wanted, 3) if wanted else None,
        # Of what it produced, how much was either confirmed or plausible-new.
        "precision": (
            round((produced_count - len(hallucinated)) / produced_count, 3)
            if produced_count else None
        ),
        "hallucination_rate": (
            round(len(hallucinated) / produced_count, 3) if produced_count else None
        ),
    }


def wilson(hits: int, total: int, z: float = 1.96) -> tuple[float, float] | None:
    """The 95% interval on a rate. `None` when there is nothing to bound.

    Because n=3 is an anecdote. A 60% acceptance from 5 findings and a 60% from
    200 are different facts, and printing them identically is how a benchmark
    starts being quoted as though it settled something.
    """
    if total <= 0:
        return None
    p = hits / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    spread = (
        z * ((p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5)
    ) / denominator
    return (round(max(0.0, centre - spread), 3), round(min(1.0, centre + spread), 3))
