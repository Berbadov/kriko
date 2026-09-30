"""A product check lands in a category pack, and the pack grows as a package.

The reader's words (B168 to B170): "Singular product searches must be addable
to the DB", "must not create a new pack each time", "must be turned into
packages". Until this module a quick look's sourced risks lived only in a job
row, and every unknown listing minted a whole pack of its own.

Nothing here knows a category. A *category pack* is an ordinary installed pack
that was authored from a draft, and everything used to pick one is read off
that pack's own data (its name, its identity keys, its subjects, the first
lines of its principle). The quick look agent is shown that list and answers
with one of its ids or nothing; `resolve` checks the answer against the list.
A category name is never typed into this file.

Three jobs, in the order a check needs them:

* **choose**: `candidates`, `choice_block`, `resolve`.
* **source**: `ground` re-checks every quote against its page, and a quote the
  page does not hold is dropped, never kept without a source. `attach` writes
  what survived into the draft as claims with evidence.
* **publish**: `install_draft` builds the draft and installs it, raising the
  draft's version when the content changed at a version the store already
  holds. `kriko.store.packstore.install` keeps its rule that a version is
  immutable; the author stops republishing one.

Every write to a draft goes through `app/packdraft.py`, so the boundary that
keeps an agent inside its own directory is the one already tested.
"""

import re
import threading
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

import yaml

from app import packauthor, packdraft
from app.findings import AGENT_CONFIDENCE
from kriko.extract.grounding import loose_span
from kriko.gates import gate_reason, structural_reasons
from kriko.pack.build import digest_of
from kriko.store import ids, packstore
from kriko.store.db import connect

__all__ = [
    "candidates", "choice_block", "resolve", "taken_ids", "ground", "attach",
    "admit", "holds",
    "absorb", "install_draft", "DraftBuildFailed", "next_version", "pick_subject",
    "MAX_CANDIDATES",
]

#: One writer at a time per process. The job runner already serialises the
#: authoring lane, but the reader's own Install press arrives on a request
#: thread, and two builds of one draft directory are how a half-written pack
#: happens.
LOCK = threading.RLock()

#: How many category packs the quick look is shown. Past this the list is a
#: catalogue, and a model choosing from a catalogue picks badly.
MAX_CANDIDATES = 12

#: Subject labels shown per pack in that list. Enough to tell two packs apart.
_SAMPLE_LABELS = 5

#: The words of a category answer that carry no meaning. A small closed
#: vocabulary of English function words, not category data.
_FILLER = frozenset({"a", "an", "the", "and", "or", "of", "for", "with", "in", "on"})


def _fold(text) -> str:
    plain = unicodedata.normalize("NFKD", str(text or "").casefold())
    return "".join(c for c in plain if not unicodedata.combining(c))


def _words(text) -> list[str]:
    return re.findall(r"[a-z0-9]+", _fold(text))


def _stem(word: str) -> str:
    """A plural folded into its singular, for comparing a category with a name.

    Deliberately crude. An irregular plural ("mice") does not fold, which only
    means the text fallback declines and the agent's own pick decides.
    """
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _stems(text) -> set[str]:
    return {_stem(word) for word in _words(text) if word not in _FILLER}


# ── choosing a category pack ─────────────────────────────────────────────


def _blurb(principle: str) -> str:
    """The first lines of a pack's own principle, as one short sentence."""
    lines = [line.strip() for line in str(principle or "").splitlines()]
    prose = [line for line in lines if line and not line.startswith("#")]
    return " ".join(prose)[:200]


def candidates(store_path) -> list[dict]:
    """Installed packs a product can join: those authored from a draft.

    A pack qualifies when its draft directory is marked as installed under the
    same id and the pack is installed and enabled in the store. First-party
    packs ship without a draft, so they are never a target; that is B170's
    "not this", and it falls out of the rule rather than being listed.
    """
    root = packdraft.drafts_root(store_path)
    if not root.is_dir():
        return []
    store = connect(store_path)
    try:
        live = {
            row["pack_id"]: row for row in store.execute(
                "SELECT pack_id, name, version FROM packs WHERE enabled = 1")
        }
    finally:
        store.close()
    found = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        pack_id = packdraft.installed_as(child)
        if not pack_id or pack_id not in live:
            continue
        try:
            state = packauthor.draft_state(store_path, child.name)
        except Exception:  # noqa: BLE001 - a draft that no longer loads is not a target
            continue
        if state.get("pack_id") != pack_id:
            continue
        found.append({
            "pack_id": pack_id,
            "slug": state["slug"],
            "name": live[pack_id]["name"],
            "version": live[pack_id]["version"],
            "identity": state.get("identity") or {},
            "subjects": list(state.get("subjects") or []),
            "blurb": _blurb(state.get("principle") or ""),
        })
        if len(found) == MAX_CANDIDATES:
            break
    return found


def taken_ids(store_path) -> list[str]:
    """Every installed pack id, so a new pack is not given one of them."""
    store = connect(store_path)
    try:
        return [row["pack_id"] for row in store.execute(
            "SELECT pack_id FROM packs ORDER BY pack_id")]
    finally:
        store.close()


def choice_block(cands: list[dict]) -> str:
    """What the quick look is shown, one pack per line. Empty when none exist."""
    lines = []
    for one in cands:
        sample = ", ".join(one["subjects"][:_SAMPLE_LABELS])
        held = f" (holds {sample})" if sample else ""
        said = f": {one['blurb']}" if one["blurb"] else ""
        lines.append(f"* `{one['pack_id']}`, {one['name']}{held}{said}")
    return "\n".join(lines)


def resolve(cands: list[dict], *, pack: str = "", category: str = "") -> dict | None:
    """The category pack an answer names, or None when nothing clearly does.

    The agent's own pick comes first and must be one of the installed ids: an
    id it invented resolves to nothing. With no pick, the category words are
    compared with each pack's name and id, and only a single pack whose words
    contain all of the category's (or the reverse) is accepted. A false join
    is worse than a second category pack, so every unclear case is "no pack"
    and a new one is authored.
    """
    wanted = str(pack or "").strip().lower()
    if wanted:
        for one in cands:
            if one["pack_id"].lower() == wanted:
                return one
    said = _stems(category)
    if not said:
        return None
    hits = []
    for one in cands:
        named = _stems(f"{one['name']} {one['pack_id'].replace('.', ' ').replace('_', ' ')}")
        if named and (said <= named or named <= said):
            hits.append(one)
    return hits[0] if len(hits) == 1 else None


# ── picking the subject a product is ─────────────────────────────────────


def pick_subject(rows: list[dict], product: str, *, floor: float = 0.0) -> dict | None:
    """The subject row that names this product best, or None below `floor`.

    A subject's label or alias is compared with the listing's title by the
    words they share, in whichever direction is larger: a listing title is
    usually the longer, a subject label the shorter, and neither is exact.
    """
    want = set(_words(product))
    best, best_score = None, -1.0
    for row in rows:
        for phrase in [row.get("label", ""), *(row.get("aliases") or [])]:
            have = set(_words(phrase))
            if not have or not want:
                continue
            shared = len(have & want)
            score = max(shared / len(have), shared / len(want))
            if score > best_score:
                best, best_score = row, score
    if best is None or best_score < floor:
        return None
    return best


# ── sources: a quote must be on its page ─────────────────────────────────


def ground(items: list[dict], fetch) -> tuple[list[dict], list[dict]]:
    """Keep the claims whose quotes are on their pages. Returns (kept, dropped).

    Each item has a `title` and an `evidence` list of `{url, quote}`. A quote
    already checked against text the plane kept (`grounded: true`) stands. Any
    other is looked up in the page: `fetch(url)` returns an object with `.text`
    ("" when the page cannot be read), each url once. The stored quote becomes
    the page's own characters, so it is a substring of the page it cites.

    A claim keeps only its grounded evidence, and a claim with none is dropped
    and named. There is no third outcome: nothing here keeps a claim without a
    source, and nothing waits for a person to decide.
    """
    pages: dict[str, str] = {}

    def page(url: str) -> str:
        if url not in pages:
            try:
                pages[url] = str(getattr(fetch(url), "text", "") or "")
            except Exception:  # noqa: BLE001 - an unreadable page is a dropped quote
                pages[url] = ""
        return pages[url]

    kept, dropped = [], []
    for item in items:
        good = []
        why = "no page and quote"
        for ev in item.get("evidence") or []:
            url = str(ev.get("url") or "").strip()
            quote = str(ev.get("quote") or "").strip()
            if not url.startswith(("http://", "https://")) or not quote:
                continue
            if ev.get("grounded"):
                good.append({"url": url, "quote": quote})
                continue
            span = loose_span(page(url), quote)
            if span:
                good.append({"url": url, "quote": span})
            else:
                why = ("the page could not be read" if not page(url)
                       else "the quote is not on the page")
        if good:
            kept.append({**item, "evidence": good})
        else:
            dropped.append({"title": item.get("title", ""), "reason": why})
    return kept, dropped


def admit(payload: dict, product: str) -> None:
    """Name the product's own subject in the reply's line-up, in place.

    A product check has already decided the category, so the one subject that
    is the product is in scope by definition. Without this, a pack whose
    line-up never named the listing's exact model would set that subject aside
    as off-category. Every other subject in the reply is still held to the
    line-up.
    """
    rows = [one for one in (payload.get("subjects") or []) if isinstance(one, dict)]
    row = pick_subject(rows, product)
    if row is not None and str(row.get("label") or "").strip():
        payload["lineup"] = [*(payload.get("lineup") or []), str(row["label"]).strip()]


def holds(store_path, slug: str, product: str) -> dict | None:
    """An amend-shaped "nothing new" answer when a draft already names the product.

    None when it does not. Lets a check of a product that is already in the
    pack succeed when the agent had nothing to add, rather than fail on an
    empty reply.
    """
    try:
        root = packdraft.open_draft(store_path, slug).root
        manifest = packdraft.load(root)
    except (packdraft.DraftRefused, OSError, ValueError):
        return None
    subjects = [one for one in _yaml_rows(root, "data/subjects.yaml")
                if isinstance(one, dict)]
    row = pick_subject(subjects, product, floor=0.75)
    if row is None:
        return None
    return {
        "slug": slug, "pack_id": manifest.pack_id, "name": manifest.name,
        "files": [], "changed": False, "subject_rows": [row],
        "subjects": len(subjects),
        "claims": len(_yaml_rows(root, "data/claims.yaml")),
        "uncovered": [], "notes": "",
    }


def _declared_domains(root: Path) -> set[str]:
    try:
        terms = yaml.safe_load(
            (root / "vocabulary" / "terms.yaml").read_text(encoding="utf-8")) or []
    except (OSError, yaml.YAMLError):
        return set()
    return {str(one.get("term_id")) for one in terms
            if isinstance(one, dict) and one.get("role") == "domain"}


def _yaml_rows(root: Path, relative: str) -> list:
    path = root / relative
    if not path.exists():
        return []
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return loaded if isinstance(loaded, list) else []


def _preamble(path: Path) -> str:
    return packauthor._preamble(path)


def _declared_keys(root: Path) -> dict[str, list[str]]:
    return dict(packdraft.load(root).identity_keys)


def _subject_id(kind: str, identity: dict, keys: dict[str, list[str]]) -> str | None:
    declared = keys.get(kind)
    if not declared or any(k not in identity for k in declared):
        return None
    return ids.subject_id(kind, {k: identity[k] for k in declared})


def _claim_row(ref: dict, item: dict, domain: str) -> dict:
    severity = str(item.get("severity") or "").strip().lower()
    return {
        "subject": ref,
        "kind": "known_issue",
        "domain": domain,
        "severity": severity if severity in {"high", "medium", "low"} else "medium",
        "detection": "reported",
        # The value `accept_findings` gives an agent-written claim, so a claim
        # ranks the same whichever door it came in by.
        "confidence": AGENT_CONFIDENCE,
        "text": {"en": {
            "title": str(item.get("title") or "").strip(),
            "body": str(item.get("body") or "").strip(),
            "advice": str(item.get("advice") or "").strip(),
        }},
        "evidence": [
            {"url": ev["url"], "quote": ev["quote"], "stance": "supports",
             "independent": True, "source_type": "page",
             "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds")}
            for ev in item.get("evidence") or []
        ],
    }


def _same_evidence(a: dict, b: dict) -> bool:
    return (ids.normalize_url(str(a.get("url") or "")) ==
            ids.normalize_url(str(b.get("url") or ""))
            and " ".join(str(a.get("quote") or "").split()).casefold() ==
            " ".join(str(b.get("quote") or "").split()).casefold())


def _owned_elsewhere(claims: list, own: int | None, ev: dict) -> bool:
    """Whether another claim of the draft already cites this page and quote."""
    return any(
        _same_evidence(ev, old)
        for at, claim in enumerate(claims)
        if at != own and isinstance(claim, dict)
        for old in claim.get("evidence") or [] if isinstance(old, dict))


def attach(store_path, slug: str, product: str, sourced: list[dict], *,
           subject_rows: list[dict] | None = None, vocab=None) -> dict:
    """Put sourced claims on the product's subject in a draft.

    The product's subject is the best match among `subject_rows` (what the
    agent's reply named), else among the draft's own subjects when the title
    plainly names one. Claims the pack's gate rows refuse are dropped, exactly
    as `accept_findings` drops them (an authored pack declares none, so it
    passes them all). A claim already there gains the new evidence instead of a
    second copy, which is how a repeat check updates its subject.

    Returns what changed. Nothing is written when nothing changed.
    """
    with LOCK:
        draft = packdraft.open_draft(store_path, slug)
        root = draft.root
        keys = _declared_keys(root)
        subjects = _yaml_rows(root, "data/subjects.yaml")
        row = pick_subject(subject_rows or [], product)
        if row is None:
            row = pick_subject(subjects, product, floor=0.75)
        out = {"subject": None, "claims_added": 0, "evidence_added": 0,
               "refused": [], "written": []}
        if row is None or not sourced:
            return out
        kind = str(row.get("kind") or "")
        identity = dict(row.get("identity") or {})
        subject_id = _subject_id(kind, identity, keys)
        if subject_id is None:
            return out
        ref = {"kind": kind, "identity": {k: identity[k] for k in keys[kind]}}
        out["subject"] = {"kind": kind, "label": row.get("label", ""),
                          "identity": ref["identity"], "subject_id": subject_id}

        domains = _declared_domains(root)
        claims = _yaml_rows(root, "data/claims.yaml")
        index = {}
        for at, existing in enumerate(claims):
            if not isinstance(existing, dict) or not isinstance(existing.get("subject"), dict):
                continue
            sid = _subject_id(str(existing["subject"].get("kind") or ""),
                              dict(existing["subject"].get("identity") or {}), keys)
            texts = existing.get("text") or {}
            primary = texts.get("en") or next(iter(texts.values()), {})
            if sid:
                index[ids.claim_id(sid, existing.get("kind", ""),
                                   existing.get("domain", ""),
                                   (primary or {}).get("title", ""))] = at

        changed = False
        for item in sourced:
            title = str(item.get("title") or "").strip()
            rationale = str(item.get("body") or "").strip()
            if vocab is not None:
                reason = gate_reason(f"{title} {rationale}", vocab, subject=title)
                reason = reason or "; ".join(
                    structural_reasons(title, rationale, vocab))
                if reason:
                    out["refused"].append({"title": title, "reason": reason})
                    continue
            wanted = str(item.get("domain") or "").strip().lower()
            domain = wanted if wanted in domains else "general"
            fresh = _claim_row(ref, item, domain)
            claim_id = ids.claim_id(subject_id, fresh["kind"], domain, title)
            at = index.get(claim_id)
            # The store keys a piece of evidence by its page and quote alone, so
            # a quote backs one claim in a pack, the first that names it. A
            # second claim built on it would open with nothing behind it. Leave
            # the quote where it is; a claim left with none is left out.
            fresh["evidence"] = [
                ev for ev in fresh["evidence"]
                if not _owned_elsewhere(claims, at, ev)]
            if not fresh["evidence"]:
                out["refused"].append({
                    "title": title,
                    "reason": "its quote already backs another claim"})
                continue
            if at is None:
                claims.append(fresh)
                index[claim_id] = len(claims) - 1
                out["claims_added"] += 1
                out["evidence_added"] += len(fresh["evidence"])
                changed = True
                continue
            have = claims[at].setdefault("evidence", [])
            for ev in fresh["evidence"]:
                if not any(_same_evidence(ev, old) for old in have):
                    have.append(ev)
                    out["evidence_added"] += 1
                    changed = True
        if changed:
            out["written"].append(packdraft.write(
                store_path, slug=slug, path="data/claims.yaml",
                text=_preamble(root / "data" / "claims.yaml")
                + yaml.safe_dump(claims, allow_unicode=True, sort_keys=False)))
        return out


# ── the pack grows as a package ──────────────────────────────────────────


def _numbers(version: str) -> tuple:
    return tuple(int("".join(ch for ch in piece if ch.isdigit()) or 0)
                 for piece in str(version).split("."))


def next_version(*seen: str) -> str:
    """The patch release above every version given.

    "0.1.0" becomes "0.1.1". A version with no digits in its last piece gains a
    ".1" rather than being guessed at. Packs are not required to use semver, so
    this only promises a version greater than each of `seen`.
    """
    seen = [one for one in seen if str(one or "").strip()]
    if not seen:
        return "0.1.0"
    top = max(seen, key=_numbers)
    pieces = str(top).split(".")
    digits = "".join(ch for ch in pieces[-1] if ch.isdigit())
    if not digits:
        return f"{top}.1"
    pieces[-1] = str(int(digits) + 1)
    return ".".join(pieces)


def _bumped_manifest(text: str, version: str) -> str:
    return re.sub(r'(?m)^(version\s*=\s*)"[^"]*"', rf'\g<1>"{version}"', text, count=1)


def absorb(store, store_path, slug: str) -> int:
    """Write claims the installed pack holds and the draft does not back into it.

    Installing replaces a pack's rows, so a claim a research run accepted
    straight into the store would vanish at the next reinstall. The draft is
    meant to be the complete record, so before a rebuild those claims are
    copied in with their evidence. Returns how many were added.
    """
    with LOCK:
        draft = packdraft.open_draft(store_path, slug)
        root = draft.root
        manifest = packdraft.load(root)
        keys = dict(manifest.identity_keys)
        pack_id = manifest.pack_id
        mine = {}
        for row in _yaml_rows(root, "data/subjects.yaml"):
            if isinstance(row, dict):
                sid = _subject_id(str(row.get("kind") or ""),
                                  dict(row.get("identity") or {}), keys)
                if sid:
                    mine[sid] = row
        claims = _yaml_rows(root, "data/claims.yaml")
        have = set()
        for existing in claims:
            if not isinstance(existing, dict) or not isinstance(existing.get("subject"), dict):
                continue
            sid = _subject_id(str(existing["subject"].get("kind") or ""),
                              dict(existing["subject"].get("identity") or {}), keys)
            texts = existing.get("text") or {}
            primary = texts.get("en") or next(iter(texts.values()), {})
            if sid:
                have.add(ids.claim_id(sid, existing.get("kind", ""),
                                      existing.get("domain", ""),
                                      (primary or {}).get("title", "")))

        added = 0
        for row in store.execute(
            "SELECT claim_id, subject_id, kind, domain, severity, consequence,"
            " detection, component, subsystem, author_confidence"
            " FROM claims WHERE pack_id = ? ORDER BY claim_id", (pack_id,),
        ).fetchall():
            if row["claim_id"] in have or row["subject_id"] not in mine:
                continue
            subject = mine[row["subject_id"]]
            kind = str(subject.get("kind") or "")
            texts = {
                one["lang"]: {"title": one["title"], "body": one["body"],
                              "advice": one["advice"]}
                for one in store.execute(
                    "SELECT lang, title, body, advice FROM claim_text"
                    " WHERE pack_id = ? AND claim_id = ? ORDER BY lang",
                    (pack_id, row["claim_id"]))
            }
            if not texts:
                continue
            evidence = [
                {"url": one["url"], "quote": one["quote"], "locator": one["locator"],
                 "stance": one["stance"], "independent": bool(one["independent"]),
                 "site": one["site_or_channel"], "source_title": one["title"],
                 "lang": one["lang"], "source_type": one["source_type"],
                 "published_at": one["published_at"],
                 "retrieved_at": one["retrieved_at"]}
                for one in store.execute(
                    "SELECT s.url, e.quote, e.locator, e.stance, e.independent,"
                    " s.site_or_channel, s.title, s.lang, s.source_type,"
                    " s.published_at, s.retrieved_at FROM evidence e"
                    " JOIN sources s ON s.source_id = e.source_id"
                    " AND s.pack_id = e.pack_id"
                    " WHERE e.pack_id = ? AND e.claim_id = ?"
                    " ORDER BY e.evidence_id", (pack_id, row["claim_id"]))
            ]
            claims.append({
                "subject": {"kind": kind, "identity": {
                    k: subject["identity"][k] for k in keys[kind]}},
                "kind": row["kind"], "domain": row["domain"],
                "severity": row["severity"], "consequence": row["consequence"],
                "detection": row["detection"], "component": row["component"],
                "subsystem": row["subsystem"],
                "confidence": row["author_confidence"],
                "text": texts, "evidence": evidence,
            })
            added += 1
        if added:
            packdraft.write(
                store_path, slug=slug, path="data/claims.yaml",
                text=_preamble(root / "data" / "claims.yaml")
                + yaml.safe_dump(claims, allow_unicode=True, sort_keys=False))
        return added


class DraftBuildFailed(ValueError):
    """The draft's own rows would not build. The answer is an edit to the draft."""


def install_draft(store_path, slug: str, *, store=None) -> dict:
    """Build a draft and install it, raising its version when it must be.

    The one way a draft reaches the store, for the product check and for the
    reader's Install press alike. The draft absorbs claims the store holds
    that it does not, builds, and is compared with what is installed:

    * the same content digest installs as a no-op (the engine's rule);
    * changed content at a version the store already holds gets the next patch
      version written into `pack.toml`, and is built again, so the digest
      advances with the version;
    * anything else installs as it stands.

    Raises what the build or the install raises. The caller decides whether a
    draft that will not install stays a draft (it does, for a product check).
    """
    with LOCK:
        own = store is None
        conn = connect(store_path) if own else store
        try:
            try:
                absorbed = absorb(conn, store_path, slug)
                artifact = packdraft.build_artifact(store_path, slug)
                root = packdraft.open_draft(store_path, slug).root
                manifest = packdraft.load(root)
                digest = digest_of(artifact)
                held = [
                    (row["version"], row["content_digest"]) for row in conn.execute(
                        "SELECT version, content_digest FROM pack_revisions"
                        " WHERE pack_id = ?", (manifest.pack_id,))
                ]
                same = any(one_digest == digest for _, one_digest in held)
                behind = [v for v, one_digest in held
                          if one_digest != digest
                          and _numbers(v) >= _numbers(manifest.version)]
                bumped = ""
                if held and not same and behind:
                    bumped = next_version(manifest.version, *behind)
                    text = (root / "pack.toml").read_text(encoding="utf-8")
                    packdraft.write(store_path, slug=slug, path="pack.toml",
                                    text=_bumped_manifest(text, bumped))
                    artifact = packdraft.build_artifact(store_path, slug)
                    digest = digest_of(artifact)
            except packdraft.DraftRefused:
                raise
            except (ValueError, OSError, yaml.YAMLError) as exc:
                raise DraftBuildFailed(str(exc)) from exc
            pack_id = packstore.install(conn, artifact)
            conn.commit()
            packdraft.mark_installed(store_path, slug, pack_id)
            version = conn.execute(
                "SELECT version FROM packs WHERE pack_id = ?", (pack_id,)
            ).fetchone()["version"]
            return {"pack_id": pack_id, "version": version, "digest": digest,
                    "bumped": bumped, "absorbed": absorbed,
                    "artifact": str(artifact)}
        finally:
            if own:
                conn.close()
