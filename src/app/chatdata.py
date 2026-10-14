"""What a chat agent may read, and only when it asks for it.

The chat screen never loads the app's data into the agent. The agent is told
the *names and one-line meanings* of the sources below, then asks for the ones
its question needs, and each source is read at that moment. So a source that
is not asked for is never read at all, and `describe_sources()` is the whole
of what the agent knows before it asks: no rows, no record, no secret.

Every source is read-only and derives everything from the stores it is given
(the engine's knowledge store and `app.sqlite`). None of them names a product,
make, model or component: the words a reader types are matched against what
the installed catalogues hold, so a new category needs no line here (G6).

Two rules a source keeps, and the dispatcher enforces the second:

* **Capped.** At most `ROWS_CAP` rows and `TEXT_CAP` characters per text field,
  so one answer cannot flood the agent's context.
* **Never raises.** A source that fails returns no rows and a note saying so;
  the agent sees the failure as data and can ask something else.

`product_match` is the searching skill. It finds candidates by the words the
agent gives it, widens the search to single words and word pairs when the full
phrase finds little, then reads each candidate's identity, attributes and
recorded risks against the reader's constraints. A constraint is `met` only by
a recorded fact that covers it; a recorded high-severity risk that covers it is
`contradicted`; no text hit at all is `unknown`, never `met`.
"""

from __future__ import annotations

import inspect
import re
import sqlite3
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass

#: Rows one source may return to the agent.
ROWS_CAP = 12
#: Characters one text field may carry to the agent.
TEXT_CAP = 400
#: Characters a note may carry.
NOTE_CAP = 300
#: Candidates `product_match` reads in full before it ranks them.
CANDIDATES_CAP = 40
#: Below this many hits the full phrase is widened to words and word pairs.
FEW_HITS = 5
#: Share of a constraint's words a fact must carry to count as `met`.
MET_AT = 0.6
#: Share of a constraint's words a high-severity risk must carry to contradict it.
CONTRADICT_AT = 0.5
#: Most recorded risks one candidate contributes to the match.
RISKS_CAP = 200

#: Small closed vocabulary: function words that never name a thing. Constants
#: are allowed here by CLAUDE.md's exception for closed sets; nothing in this
#: list grows with coverage.
STOP = frozenset("""
a about above an and are around as at be below by can could do does for from
had has have how i if in into is it its just less like me more most much my
need needs no not of off on or our out over should so some than that the their
them then there these this those to too under up us very want wants was we
were what when which while who why will with without would you your
""".split())


@dataclass
class Context:
    """What a source may read: the engine's store and the app's own file.

    Either may be None when there is nothing to read yet (a fresh install has
    no store file). A source then answers with no rows and a note, never an
    error.
    """

    store: sqlite3.Connection | None = None
    app: sqlite3.Connection | None = None


@dataclass(frozen=True)
class Source:
    name: str
    description: str
    #: Argument name -> one-line meaning. The only arguments the agent may pass.
    args: dict
    #: What the rows are, in words: "read 4 <noun>", "no rows from <noun>".
    noun: str
    #: The step's label while it runs, from the arguments it was given.
    doing: Callable[[dict], str]
    run: Callable[..., dict]
    #: Arguments that are lists of phrases rather than one string.
    lists: tuple = ()


# ── text helpers ─────────────────────────────────────────────────────────


def _fold(text) -> str:
    folded = unicodedata.normalize("NFKD", str(text or "").casefold())
    return "".join(c for c in folded if not unicodedata.combining(c))


def _content(text) -> list[str]:
    """The content words of a phrase, in order, without repeats.

    Letters and digits split apart, so `500mm` reads as `500` and `mm`, and
    `18V` as `18` and `v`. A single letter is a unit only when a digit sits
    beside it, so it is kept there and dropped anywhere else; digits are kept
    whatever their length.
    """
    tokens = re.findall(r"[a-z]+|\d+", _fold(text))
    seen: list[str] = []
    for index, token in enumerate(tokens):
        if token in STOP:
            continue
        if token.isalpha() and len(token) < 2:
            beside_digits = any(
                0 <= near < len(tokens) and tokens[near].isdigit()
                for near in (index - 1, index + 1))
            if not beside_digits:
                continue
        if token not in seen:
            seen.append(token)
    return seen


def _same(one: str, other: str) -> bool:
    """Equal words, or one is the start of a longer word of four letters or more.

    `plastic` matches `plastics`; `500` does not match `5000`.
    """
    if one == other:
        return True
    if min(len(one), len(other)) < 4 or one.isdigit() or other.isdigit():
        return False
    return one.startswith(other) or other.startswith(one)


def _coverage(phrase: list[str], text: str) -> float:
    """The share of a phrase's content words that the text carries."""
    if not phrase:
        return 0.0
    words = re.findall(r"[a-z]+|\d+", _fold(text))
    hit = sum(1 for one in phrase if any(_same(one, word) for word in words))
    return hit / len(phrase)


def _clip(text, limit: int = TEXT_CAP) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _tidy(value, truncated: list[bool]):
    """Clip every string and cap every list, recording whether anything was cut."""
    if isinstance(value, str):
        clipped = _clip(value)
        if clipped != value:
            truncated[0] = True
        return clipped
    if isinstance(value, dict):
        return {key: _tidy(one, truncated) for key, one in value.items()}
    if isinstance(value, list | tuple):
        if len(value) > ROWS_CAP:
            truncated[0] = True
        return [_tidy(one, truncated) for one in list(value)[:ROWS_CAP]]
    return value


def _words_to_search(text: str) -> list[str]:
    """The words of a query as a search box would take them, stop words out."""
    out: list[str] = []
    for raw in str(text or "").split():
        word = raw.strip(".,;:!?()[]\"'`").lower()
        if len(word) < 2 or word in STOP or word in out:
            continue
        out.append(word)
    return out


def _result(rows=(), note: str = "", **extra) -> dict:
    return {"rows": list(rows), "truncated": False, "note": _clip(note, NOTE_CAP), **extra}


def _empty(note: str) -> dict:
    return _result((), note)


_NO_PACKS = "the engine store has no packs yet"
_NO_APP = "the app's own records are not open"


def _matches(text_parts, query: str) -> bool:
    """Every content word of the query appears somewhere in the parts (no query: all)."""
    words = _content(query)
    if not words:
        return True
    text = " ".join(str(part) for part in text_parts)
    return all(any(_same(word, found) for found in _content(text)) for word in words)


# ── the engine's knowledge, read per subject ─────────────────────────────


def _facts(store, subject_id: str, pack_id: str) -> list[dict]:
    """What the catalogue states about one subject, identity first."""
    return [
        {
            "text": " ".join(part for part in (row["key"], row["value_text"], row["unit"]) if part),
            "key": row["key"],
            "value": row["value_text"],
            "unit": row["unit"],
            "identity": bool(row["is_identity"]),
            "source": row["source_url"] or "",
        }
        for row in store.execute(
            "SELECT key, value_text, unit, is_identity, source_url FROM attributes"
            " WHERE pack_id = ? AND subject_id = ? ORDER BY is_identity DESC, key",
            (pack_id, subject_id))
    ]


def _risks(store, subject_id: str, pack_id: str) -> list[dict]:
    """The recorded risks a subject serves, relations included, with their sources.

    Reached the same way the lookup reaches them (`expand`), so a risk on a
    shared part counts for the product that carries the part.
    """
    from kriko.lookup.match import expand

    reached = set(expand(store, (subject_id,), (pack_id,))) | {subject_id}
    marks = ",".join("?" * len(reached))
    claims = store.execute(
        f"SELECT c.claim_id, c.severity, c.kind, c.subject_id FROM claims c"
        f" WHERE c.pack_id = ? AND c.subject_id IN ({marks})"
        f" ORDER BY c.claim_id LIMIT ?",
        (pack_id, *reached, RISKS_CAP)).fetchall()
    if not claims:
        return []
    ids = [row["claim_id"] for row in claims]
    idmarks = ",".join("?" * len(ids))
    titles: dict[str, tuple[str, str]] = {}
    for row in store.execute(
            f"SELECT claim_id, lang, title, body FROM claim_text"
            f" WHERE pack_id = ? AND claim_id IN ({idmarks})", (pack_id, *ids)):
        # English when the pack has it, otherwise whichever language it has.
        if row["claim_id"] not in titles or row["lang"] == "en":
            titles[row["claim_id"]] = (row["title"], row["body"])
    evidence: dict[str, list[dict]] = {}
    for row in store.execute(
            f"SELECT e.claim_id, e.quote, s.url FROM evidence e"
            f" JOIN sources s USING (source_id, pack_id)"
            f" WHERE e.pack_id = ? AND e.claim_id IN ({idmarks})", (pack_id, *ids)):
        evidence.setdefault(row["claim_id"], []).append(
            {"url": row["url"], "quote": row["quote"]})
    out = []
    for row in claims:
        title, body = titles.get(row["claim_id"], ("", ""))
        cited = evidence.get(row["claim_id"], [])[:2]
        out.append({
            "claim_id": row["claim_id"],
            "title": title,
            "body": body,
            "severity": row["severity"],
            "kind": row["kind"],
            "text": f"{title}. {body[:300]}",
            "source": cited[0]["url"] if cited else "",
            "sources": cited,
        })
    return out


def _subject_row(store, subject_id: str, pack_id: str, label: str, kind: str,
                 identity: dict | None = None) -> dict:
    risks = _risks(store, subject_id, pack_id)
    return {
        "subject_id": subject_id, "pack_id": pack_id, "label": label, "kind": kind,
        "identity": identity or {},
        "claims": len(risks),
        "risks": [{"title": r["title"], "severity": r["severity"], "kind": r["kind"],
                   "sources": r["sources"]} for r in risks],
    }


# ── the sources ──────────────────────────────────────────────────────────


def _catalogue_search(ctx: Context, query: str = "", kind: str = "") -> dict:
    from kriko.lookup import find

    store = ctx.store
    if store is None:
        return _empty(_NO_PACKS)
    if not _words_to_search(query):
        return _empty("say what to look for")
    hits = find.search(store, query, kind=kind, limit=find.LIMIT)
    rows = [
        {"subject_id": h["subject_id"], "pack_id": h["pack_id"], "label": h.get("label", ""),
         "kind": h.get("kind", ""), "identity": h.get("identity") or {},
         "claims": h.get("claims", 0), "why": h.get("why", [])}
        for h in hits
    ]
    return _result(rows, "" if rows else "no product in the catalogue matches those words")


def _gather(conn, query: str, pack_ids, kind: str) -> tuple[list[dict], int]:
    """Candidates for a need, from the whole phrase and then from its parts."""
    from kriko.lookup import find

    merged: dict[tuple, dict] = {}
    searches = 0

    def search(text: str) -> None:
        nonlocal searches
        searches += 1
        for hit in find.search(conn, text, pack_ids=pack_ids, kind=kind, limit=find.LIMIT):
            merged.setdefault((hit["subject_id"], hit["pack_id"]), hit)

    search(query)
    if len(merged) < FEW_HITS:
        words = _words_to_search(query)[:8]
        for word in words:
            search(word)
        for first, second in list(zip(words, words[1:]))[:6]:
            search(f"{first} {second}")
    return list(merged.values())[:CANDIDATES_CAP], searches


def _judge(phrase: str, facts: list[dict], risks: list[dict]) -> dict:
    """One constraint against one candidate: met, contradicted or unknown.

    `contradicted` is checked first: a recorded serious risk that names the
    constraint's subject outweighs a fact that happens to share a word with it.
    """
    words = _content(phrase)
    row = {"text": _clip(phrase, 200), "status": "unknown", "evidence": "", "source": ""}
    if not words:
        return row
    contra = [(_coverage(words, r["text"]), r) for r in risks if r["severity"] == "high"]
    contra = [(score, r) for score, r in contra if score >= CONTRADICT_AT]
    if contra:
        score, risk = max(contra, key=lambda pair: pair[0])
        row.update(status="contradicted", evidence=_clip(risk["title"] or risk["text"]),
                   source=risk["source"])
        return row
    stated = [(_coverage(words, f["text"]), f) for f in facts]
    stated = [(score, f) for score, f in stated if score >= MET_AT]
    if stated:
        score, fact = max(stated, key=lambda pair: (pair[0], pair[1]["identity"]))
        row.update(status="met", evidence=_clip(fact["text"]), source=fact["source"])
    return row


def _evaluate(conn, hit: dict, must: list[str], prefer: list[str]) -> dict:
    sid, pid = hit["subject_id"], hit["pack_id"]
    facts = _facts(conn, sid, pid)
    risks = _risks(conn, sid, pid)
    must_rows = [_judge(p, facts, risks) for p in must]
    prefer_rows = [_judge(p, facts, risks) for p in prefer]
    everything = must_rows + prefer_rows
    return {
        "subject_id": sid, "pack_id": pid,
        "label": hit.get("label", ""), "kind": hit.get("kind", ""),
        "identity": hit.get("identity") or {},
        "claims": len(risks),
        "all_musts_met": all(r["status"] == "met" for r in must_rows),
        "contradicted_musts": sum(r["status"] == "contradicted" for r in must_rows),
        "unknown": sum(r["status"] == "unknown" for r in everything),
        "prefs_met": sum(r["status"] == "met" for r in prefer_rows),
        "serious": sum(r["severity"] == "high" for r in risks),
        "must": must_rows,
        "prefer": prefer_rows,
    }


def _rank_key(row: dict) -> tuple:
    """Musts first (all met, then fewest contradicted, then fewest unknown),
    then the preferences met, then the fewest serious risks. Total: ties fall
    to the label and the id, so the same question reads the same way twice."""
    return (not row["all_musts_met"], row["contradicted_musts"], row["unknown"],
            -row["prefs_met"], row["serious"], row["label"], row["subject_id"])


def _product_match(ctx: Context, query: str = "", must: list | None = None,
                   prefer: list | None = None, kind: str = "", pack_id: str = "") -> dict:
    store = ctx.store
    if store is None:
        return _empty("the engine store has no packs yet")
    must_list = list(must or [])
    prefer_list = list(prefer or [])
    text = query.strip() or " ".join(must_list + prefer_list)
    if not _words_to_search(text):
        return _empty("say what the product is, in words")
    pack_ids = [pack_id] if pack_id else None
    candidates, searches = _gather(store, text, pack_ids, kind)
    rows = [_evaluate(store, hit, must_list, prefer_list) for hit in candidates]
    rows.sort(key=_rank_key)
    for position, row in enumerate(rows, start=1):
        row["rank"] = position
    note = (f"{len(rows)} candidate(s) from {searches} search(es)" if rows
            else f"no candidate from {searches} search(es): try other words for the product")
    return _result(rows[:ROWS_CAP], note, truncated=len(rows) > ROWS_CAP)


def _subject_detail(ctx: Context, subject_id: str = "") -> dict:
    store = ctx.store
    if store is None:
        return _empty(_NO_PACKS)
    row = store.execute(
        "SELECT subject_id, pack_id, kind, label FROM subjects WHERE subject_id = ?",
        (subject_id,)).fetchone()
    if row is None:
        return _empty(f"no product with id {subject_id}")
    facts = _facts(store, row["subject_id"], row["pack_id"])
    relations = [
        {"predicate": rel["predicate"], "object": (store.execute(
            "SELECT label FROM subjects WHERE subject_id = ?",
            (rel["object_id"],)).fetchone() or {"label": rel["object_id"]})["label"]}
        for rel in store.execute(
            "SELECT predicate, object_id FROM relations WHERE subject_id = ? AND pack_id = ?"
            " ORDER BY predicate", (row["subject_id"], row["pack_id"]))
    ]
    detail = _subject_row(store, row["subject_id"], row["pack_id"], row["label"],
                          row["kind"], {f["key"]: f["value"] for f in facts if f["identity"]})
    detail["attributes"] = [{"key": f["key"], "value": f["value"], "unit": f["unit"]}
                            for f in facts if not f["identity"]]
    detail["relations"] = relations
    return _result([detail])


def _saved_checks(ctx: Context, text: str = "") -> dict:
    from app.web import state

    records = ctx.app
    if records is None:
        return _empty(_NO_APP)
    rows = []
    for item in state.recent(records, limit=200):
        stored = state.get_lookup(records, item["lookup_id"]) or {}
        response = stored.get("response") or {}
        titles = [str(c.get("title", "")) for c in response.get("claims") or [] if isinstance(c, dict)]
        if not _matches([item["label"], *titles], text):
            continue
        rows.append({"lookup_id": item["lookup_id"], "label": item["label"],
                     "created_at": item["created_at"], "risks": len(titles),
                     "risk_titles": titles[:6], "packs": item["pack_ids"]})
    return _result(rows, "" if rows else "no saved check matches those words")


def _quick_looks(ctx: Context, text: str = "") -> dict:
    from app.web import state

    records = ctx.app
    if records is None:
        return _empty(_NO_APP)
    rows = []
    for job in state.list_jobs(records, limit=200):
        if job["kind"] != "quick_look" or job["state"] != state.SUCCEEDED:
            continue
        result = job.get("result") or {}
        risks = [r for r in result.get("risks") or [] if isinstance(r, dict)]
        product = str(job["params"].get("product", ""))
        if not _matches([product, result.get("category", ""),
                         *(r.get("title", "") for r in risks)], text):
            continue
        rows.append({"job_id": job["job_id"], "product": product,
                     "category": result.get("category", ""), "risks": len(risks),
                     "risk_titles": [str(r.get("title", "")) for r in risks[:6]],
                     "created_at": job["created_at"]})
    return _result(rows, "" if rows else "no quick look matches those words")


def _compare_drafts(ctx: Context, text: str = "") -> dict:
    from app.web import state

    records = ctx.app
    if records is None:
        return _empty(_NO_APP)
    rows = []
    for draft in state.compare_drafts(records):
        questions = state.compare_questions(records, draft["draft_id"])
        asked = [{"question": q["question"], "answer": q["answer"]} for q in questions[:3]]
        if not _matches([draft["name"], *(q["question"] for q in asked)], text):
            continue
        rows.append({"draft_id": draft["draft_id"], "name": draft["name"],
                     "checks": len(draft["lookup_ids"]), "questions": asked})
    return _result(rows, "" if rows else "no compare draft matches those words")


def _activity(ctx: Context, text: str = "") -> dict:
    from app.web import state

    records = ctx.app
    if records is None:
        return _empty(_NO_APP)
    rows = [
        {"kind": job["kind"], "state": job["state"], "message": job.get("message") or "",
         "created_at": job["created_at"]}
        for job in state.list_jobs(records, limit=40)
        if _matches([job["kind"], job.get("message") or ""], text)
    ]
    return _result(rows, "" if rows else "no recent activity matches those words")


def _research_runs(ctx: Context, text: str = "") -> dict:
    from app.web import state

    records = ctx.app
    if records is None:
        return _empty(_NO_APP)
    rows = []
    for run in state.research_runs(records, limit=12):
        titles = [c["title"] for c in state.run_claims(records, run["run_id"])
                  if not c["removed_at"]]
        if not _matches([run["llm"], *titles], text):
            continue
        rows.append({"run_id": run["run_id"], "started_at": run["started_at"],
                     "outcome": run["outcome"], "claims": run["claims"],
                     "removed": run["removed"], "spent_usd": run["spent_usd"],
                     "claim_titles": titles[:6]})
    kept = state.documents_kept(records)
    return _result(rows, f"{kept['documents']} source page(s) kept for re-checking")


def _packs(ctx: Context) -> dict:
    store = ctx.store
    if store is None:
        return _empty(_NO_PACKS)
    rows = [
        {"pack_id": r["pack_id"], "name": r["name"], "version": r["version"],
         "enabled": bool(r["enabled"]), "subjects": r["subjects"], "claims": r["claims"]}
        for r in store.execute(
            "SELECT p.pack_id, p.name, p.version, p.enabled,"
            " (SELECT COUNT(*) FROM subjects s WHERE s.pack_id = p.pack_id) AS subjects,"
            " (SELECT COUNT(*) FROM claims c WHERE c.pack_id = p.pack_id) AS claims"
            " FROM packs p ORDER BY p.pack_id")
    ]
    return _result(rows, "" if rows else "no catalogue is installed")


def _sites(ctx: Context) -> dict:
    from app import sites

    store = ctx.store
    if store is None:
        return _empty(_NO_PACKS)
    readable = [{"site": one["site"], "status": "readable", "source": one.get("source", "")}
                for one in sites.registered(store, ctx.app)]
    asked = [{"site": row["host"], "status": "asked for, not readable yet",
              "source": "request"} for row in sites.requested(store, ctx.app)]
    return _result(readable + asked, "" if readable or asked else "no site is registered")


def _coverage_gaps(ctx: Context, pack_id: str = "") -> dict:
    from app import agenda

    store = ctx.store
    if store is None:
        return _empty(_NO_PACKS)
    report = agenda.compute(store, ctx.app, None, pack_id, ROWS_CAP)
    rows = [{"kind": r["kind"], "subject_id": r.get("subject_id", ""),
             "pack_id": r.get("pack_id", ""), "label": r.get("label", ""),
             "why": r.get("why", "")} for r in report.get("rows", [])]
    return _result(rows, report.get("note", ""))


# ── the registry ─────────────────────────────────────────────────────────


def _quoted(args: dict) -> str:
    return f"“{args['query']}”" if args.get("query") else "the need"


SOURCES: dict[str, Source] = {s.name: s for s in (
    Source(
        "product_match",
        "Finds the products that fit a need and checks each reader constraint "
        "against what is recorded: met, unknown or contradicted, ranked.",
        {"query": "the product, in words", "must": "hard constraints, one phrase each",
         "prefer": "preferences, one phrase each", "kind": "optional kind of product",
         "pack_id": "optional catalogue to search"},
        "products", lambda a: f"searching the catalogue for {_quoted(a)}",
        _product_match, lists=("must", "prefer")),
    Source(
        "catalogue_search",
        "Finds products in the installed catalogues by their names and identity values.",
        {"query": "words the product's name or identity contains", "kind": "optional kind"},
        "products", lambda a: f"searching the catalogue for {_quoted(a)}", _catalogue_search),
    Source(
        "subject_detail",
        "One product's attributes, relations and recorded risks, each with its source page.",
        {"subject_id": "the product id, from a search"},
        "product records", lambda a: "reading one product's record", _subject_detail),
    Source(
        "saved_checks",
        "The checks the reader saved, with the risks each one recorded.",
        {"text": "optional words the check should contain"},
        "saved checks", lambda a: "reading saved checks", _saved_checks),
    Source(
        "quick_looks",
        "Quick looks the reader ran on products, with their category and risks.",
        {"text": "optional words the look should contain"},
        "quick looks", lambda a: "reading quick looks", _quick_looks),
    Source(
        "compare_drafts",
        "The named comparisons the reader kept, and the questions asked about them.",
        {"text": "optional words the draft should contain"},
        "compare drafts", lambda a: "reading compare drafts", _compare_drafts),
    Source(
        "activity",
        "Recent jobs and what they reported: kind, state and message.",
        {"text": "optional words to look for"},
        "activity entries", lambda a: "reading recent activity", _activity),
    Source(
        "research_runs",
        "Research runs: what they found, what they cost and the claims they kept.",
        {"text": "optional words a run's claims should contain"},
        "research runs", lambda a: "reading research runs", _research_runs),
    Source(
        "packs",
        "The installed catalogues, their versions and how much each one holds.",
        {}, "catalogues", lambda a: "reading the installed catalogues", _packs),
    Source(
        "sites",
        "The websites Kriko can read, and any the reader asked for that it cannot yet.",
        {}, "sites", lambda a: "reading the list of sites", _sites),
    Source(
        "coverage_gaps",
        "What is known to be missing: products with no recorded risks, and thin records.",
        {"pack_id": "optional catalogue to look at"},
        "gaps", lambda a: "reading what is missing", _coverage_gaps),
)}


def describe_sources() -> list[dict]:
    """The names, meanings and argument names of every source, and nothing else.

    This is all the agent sees before it asks. It carries no row, no record
    and no count, so asking costs what the question needs and no more.
    """
    return [
        {"name": s.name, "description": s.description, "args": dict(s.args)}
        for s in SOURCES.values()
    ]


def _arguments(source: Source, args: dict) -> tuple[dict, list[str]]:
    """Only the arguments the source declares, coerced to their types.

    An argument the source does not declare is dropped and named in the note:
    the agent's extra words never reach a function as keyword arguments.
    """
    accepted: dict = {}
    ignored: list[str] = []
    declared = set(inspect.signature(source.run).parameters) - {"ctx"}
    for key, value in (args or {}).items():
        if key not in declared:
            ignored.append(str(key))
            continue
        if key in source.lists:
            items = value if isinstance(value, list) else [value]
            phrases: list[str] = [_clip(item, 200) for item in items if str(item).strip()]
            accepted[key] = phrases[:12]
        else:
            accepted[key] = _clip(value, 300) if value is not None else ""
    return accepted, ignored


def run(name: str, ctx: Context, args: dict | None = None) -> dict:
    """Read one source. Never raises; an unknown name is an error, reported as data."""
    source = SOURCES.get(name)
    if source is None:
        return {"source": name, "rows": [], "truncated": False, "error": True,
                "note": f"there is no source called {_clip(name, 60)!r}"}
    try:
        accepted, ignored = _arguments(source, args or {})
        out = source.run(ctx, **accepted)
    except Exception as exc:  # noqa: BLE001 - a failed read is data, never a crash
        out = {"rows": [], "truncated": False, "note": f"could not read {name}: {type(exc).__name__}"}
    note = out.get("note", "")
    if ignored:
        note = f"{note}; ignored {', '.join(ignored)}".lstrip("; ")
    flags = [False]
    rows = _tidy(list(out.get("rows") or []), flags)
    return {
        "source": name,
        "rows": rows,
        "truncated": bool(out.get("truncated")) or flags[0],
        "note": _clip(note, NOTE_CAP),
        "error": bool(out.get("error", False)),
    }


def noun(name: str) -> str:
    source = SOURCES.get(name)
    return source.noun if source else "rows"


def label(name: str, args: dict | None = None) -> str:
    """What a step says while it runs."""
    source = SOURCES.get(name)
    if source is None:
        return f"no source called {_clip(name, 60)!r}"
    return source.doing(args or {})
