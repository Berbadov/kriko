"""The one place a researched product is known, saved and found again.

Before this module a finished research, a queued listing and the Compare list
each answered "which product is this?" by their own rule, and disagreed:

* A queued listing was matched by searching its seller's whole title, with
  every word required in some label (`find.search`). A title almost never has
  only the catalog's words in it, so a product the catalog already held was
  "not in your catalogs" and was researched again.
* A finished research wrote claims into a catalog and left no saved check, so
  the Compare list, which lists saved checks, never showed it.

Here the rules are: a product is the subject a finished job says it produced,
or the stored answer the listing was queued with, or else an installed subject
whose own words all appear in the listing's title (the longest such name
wins, and two equally long ones are refused rather than guessed). A product has
at most one saved check, refreshed in place when research adds to it.

App state only: `product_checks` and the lookups it points at live in
`app.sqlite`; the catalog is read, never written.
"""

from __future__ import annotations

import re
import unicodedata

from app.web import state

#: What a queued product that no installed catalog names is called. The queue
#: reads this exact text to say the product needs an agent.
NOT_IN_CATALOGS = "not in your catalogs"

#: The job kinds whose finished result files claims into a catalog and so
#: names the product they researched. A quick look on its own files nothing.
FILING_KINDS = ("research", "pack_author", "pack_harvest")


class ProductNotFound(LookupError):
    """No installed product matches. The message is the reason, said to the reader."""


class ProductAmbiguous(ValueError):
    """More than one installed product fits, equally well. Named, never guessed."""


def _words(text) -> set[str]:
    plain = unicodedata.normalize("NFKD", str(text or "").casefold())
    folded = "".join(c for c in plain if not unicodedata.combining(c))
    return set(re.findall(r"[a-z0-9]+", folded))


def enabled_subject(store, subject_id: str) -> dict | None:
    """The subject, when its pack is installed and enabled; None otherwise."""
    row = store.execute(
        "SELECT s.subject_id, s.pack_id, s.kind, s.label FROM subjects s"
        " JOIN packs p USING (pack_id)"
        " WHERE s.subject_id = ? AND p.enabled = 1",
        (subject_id,),
    ).fetchone()
    return dict(row) if row else None


def identity_of(store, subject_id: str, pack_id: str) -> dict:
    """The identity keys a subject is known by, as the lookup takes them."""
    return {row["key"]: row["value_text"] for row in store.execute(
        "SELECT key, value_text FROM attributes"
        " WHERE subject_id = ? AND pack_id = ? AND is_identity = 1 ORDER BY key",
        (subject_id, pack_id))}


def _target(row: dict) -> dict:
    return {"subject_id": row["subject_id"], "pack_id": row["pack_id"],
            "kind": row["kind"], "label": row["label"]}


def ensure_check(app_state, store, subject_id: str) -> dict:
    """The saved check for one installed product, made or refreshed in place.

    The answer is the engine's own lookup on the product's identity, so it is
    what a check of the product would say today. One row per product: a second
    call refreshes the same saved check rather than adding a row to Compare.
    Raises `ProductNotFound` when no enabled catalog holds the product, and
    `ValueError` when it has no identity keys to look it up by.
    """
    from app.web.routers.query import LookupRequest, answer

    row = enabled_subject(store, subject_id)
    if row is None:
        raise ProductNotFound(f"no installed product {subject_id}")
    identity = identity_of(store, row["subject_id"], row["pack_id"])
    if not identity:
        raise ValueError("this product has no identity keys to check it by")
    body = LookupRequest(kind=row["kind"], identity=identity)
    payload, _result = answer(store, body)

    prior = app_state.execute(
        "SELECT lookup_id FROM product_checks WHERE subject_id = ? AND pack_id = ?",
        (row["subject_id"], row["pack_id"])).fetchone()
    lookup_id = prior["lookup_id"] if prior else ""
    if lookup_id and state.get_lookup(app_state, lookup_id) is not None:
        state.replace_response(app_state, lookup_id, payload)
    else:
        lookup_id = state.record_lookup(
            app_state, source="product",
            label=row["label"] or " ".join(identity.values()),
            request=body.model_dump(), response=payload)
        app_state.execute(
            "INSERT OR REPLACE INTO product_checks (subject_id, pack_id, lookup_id)"
            " VALUES (?, ?, ?)", (row["subject_id"], row["pack_id"], lookup_id))
        app_state.commit()
    payload["lookup_id"] = lookup_id
    return payload


def _named_by(kind: str, result: dict) -> tuple[str, str]:
    """The (subject_id, pack_id) a finished job's result names, or empty strings."""
    if kind == "research":
        return str(result.get("subject_id") or ""), str(result.get("pack_id") or "")
    if kind == "pack_author":
        subject = result.get("subject")
        sid = subject.get("subject_id") if isinstance(subject, dict) else None
        return str(sid or ""), str(result.get("pack_id") or "")
    return "", ""


def record_finished(app_state, store, kind: str, result) -> list[str]:
    """Save the product check for every product a finished job filed claims for.

    Called once a job has succeeded, from the runner, so a finished research
    shows in Compare without anyone pressing anything. Returns the subject ids
    saved. A job whose product is not installed (a draft kept back) saves
    nothing and is not an error here: the queue reports that when it asks.
    """
    if kind not in FILING_KINDS or not isinstance(result, dict):
        return []
    if kind == "pack_harvest":
        pairs = [(str(one.get("subject_id") or ""), str(one.get("pack_id") or ""))
                 for one in result.get("filed_subjects") or [] if isinstance(one, dict)]
    else:
        pairs = [_named_by(kind, result)]
    saved = []
    for subject_id, pack_id in pairs:
        if not subject_id:
            continue
        row = enabled_subject(store, subject_id)
        if row is None or (pack_id and row["pack_id"] != pack_id):
            continue
        ensure_check(app_state, store, subject_id)
        saved.append(subject_id)
    return saved


def _named_subjects(store, text: str) -> list[tuple[int, dict]]:
    """Installed subjects whose label or alias words all appear in `text`.

    The other way round from the search box: there every word typed must be
    in the catalog; here every word of the catalog's name must be in the
    listing. Returns (words matched, subject) for each subject that fits.
    """
    wanted = _words(text)
    if not wanted:
        return []
    subjects: dict[tuple[str, str], dict] = {}
    for row in store.execute(
        "SELECT s.subject_id, s.pack_id, s.kind, s.label FROM subjects s"
        " JOIN packs p USING (pack_id) WHERE p.enabled = 1"):
        subjects[(row["subject_id"], row["pack_id"])] = {
            "row": dict(row), "phrases": [row["label"] or ""]}
    for row in store.execute(
        "SELECT a.subject_id, a.pack_id, a.alias FROM subject_aliases a"
        " JOIN packs p USING (pack_id) WHERE p.enabled = 1"):
        entry = subjects.get((row["subject_id"], row["pack_id"]))
        if entry is not None:
            entry["phrases"].append(row["alias"] or "")
    hits = []
    for entry in subjects.values():
        best = 0
        for phrase in entry["phrases"]:
            words = _words(phrase)
            if words and words <= wanted:
                best = max(best, len(words))
        if best:
            hits.append((best, entry["row"]))
    return hits


def _stored_subject(app_state, store, lookup_id: str) -> dict | None:
    """The product a saved check answered for, when it is still installed."""
    saved = state.get_lookup(app_state, lookup_id)
    if saved is None:
        return None
    for named in (saved.get("response") or {}).get("subjects") or []:
        subject_id = named if isinstance(named, str) else str((named or {}).get("subject_id") or "")
        row = enabled_subject(store, subject_id) if subject_id else None
        if row is not None:
            return row
    return None


def resolve(app_state, store, item: dict, job: dict | None = None) -> dict:
    """The installed product a queued row stands for.

    With a finished `job`, the product that job produced, and the reason when
    it is not installed (its install error, when the job kept one). Otherwise
    the product the row's stored answer named, else the subject its title
    names. Raises `ProductNotFound` (the reason, said plainly) or
    `ProductAmbiguous`.
    """
    if job is not None:
        result = job.get("result") or {}
        subject_id, _pack_id = _named_by(str(job.get("kind") or ""), result)
        row = enabled_subject(store, subject_id) if subject_id else None
        if row is not None:
            return _target(row)
        why = str(result.get("install_error") or "").strip()
        if subject_id:
            raise ProductNotFound(
                "researched, but the product did not install"
                + (f": {why}" if why else " into an installed catalog"))
        raise ProductNotFound("researched, but the job names no product")

    if item.get("lookup_id"):
        row = _stored_subject(app_state, store, item["lookup_id"])
        if row is not None:
            return _target(row)

    hits = _named_subjects(store, item.get("name") or "")
    if not hits:
        raise ProductNotFound(NOT_IN_CATALOGS)
    best = max(words for words, _row in hits)
    top = {(row["subject_id"], row["pack_id"]): row
           for words, row in hits if words == best}
    if len(top) > 1:
        names = sorted(row["label"] or row["subject_id"] for row in top.values())
        raise ProductAmbiguous(
            f"{len(names)} installed products fit this name: {', '.join(names)}; "
            "choose one in Browse")
    return _target(next(iter(top.values())))
