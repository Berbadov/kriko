"""Compile a pack directory into a distributable pack file.

Authoring is YAML; the artifact is SQLite. One generic builder serves every
pack, so onboarding a product category never requires a line of Python — see
CLAUDE.md's scalability principle. A pack that needs bespoke import logic
(migrating years of legacy data recorded in inconsistent shapes, say) ships
its own script that emits this same standard layout.

Expected layout:

    pack.toml
    vocabulary/terms.yaml      attribute/predicate/domain definitions + aliases
    data/subjects.yaml         subjects, their attributes, aliases, relations
    data/claims.yaml           claims, text per language, conditions, evidence

Validation is strict on purpose. A claim pointing at a subject that does not
exist, or an attribute using a key the vocabulary never declared, fails the
build rather than shipping a row nobody will ever see. Silent data loss in a
knowledge base is worse than a failed build.
"""

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from kriko.pack.manifest import load as load_manifest
from kriko.store import ids
from kriko.store.db import SCHEMA_VERSION, connect

_NUMERIC_TYPES = {"number", "year"}
_GATE_KINDS = ("covered", "generic", "ambiguous", "exempt", "noise", "specificity", "limits")


def _load_yaml(path: Path, default):
    if not path.exists():
        return default
    return yaml.safe_load(path.read_text(encoding="utf-8")) or default


def _as_number(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _domain_of(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _subject_key(entry: dict, identity_keys: dict) -> tuple[str, str]:
    """Resolve a subject reference (kind + identity dict) to its content hash."""
    kind = entry.get("kind")
    identity = entry.get("identity") or {}
    if not kind:
        raise ValueError(f"subject reference has no kind: {entry!r}")
    declared = identity_keys.get(kind)
    if declared is None:
        raise ValueError(f"subject kind {kind!r} has no [identity] entry in pack.toml")
    missing = [k for k in declared if k not in identity]
    if missing:
        raise ValueError(
            f"subject {entry!r} is missing identity key(s) {missing} "
            f"declared for kind {kind!r}"
        )
    return kind, ids.subject_id(kind, {k: identity[k] for k in declared})


def _gate_rows(spec) -> list[tuple[str, str, str]]:
    """Flatten vocabulary/gates.yaml into validated gate rows."""
    if not spec:
        return []
    if not isinstance(spec, dict):
        raise ValueError(
            "vocabulary/gates.yaml must be a mapping of rule kind to term "
            f"list; got {type(spec).__name__}."
        )

    unknown = set(spec) - set(_GATE_KINDS)
    if unknown:
        raise ValueError(
            f"vocabulary/gates.yaml has unknown rule kinds {sorted(unknown)}; "
            f"known kinds are {list(_GATE_KINDS)}."
        )

    rows = []
    for kind in _GATE_KINDS:
        for entry in spec.get(kind) or []:
            if isinstance(entry, dict):
                if "pattern" not in entry:
                    raise ValueError(
                        f"vocabulary/gates.yaml {kind!r} entry has no pattern"
                    )
                rows.append((kind, str(entry["pattern"]), str(entry.get("note", ""))))
            else:
                rows.append((kind, str(entry), ""))
    return rows


def _tier_rows(spec) -> list[tuple[str, str, str]]:
    """A pack's trust file, translated into the patterns `tier_of` reads.

    The pack author writes three human things — a table of domains, a few
    "anything containing this" rules, and a fallback. The engine reads one
    thing: a pattern-to-tier map where `*x*` means contains and `*` means
    everything else. Translating here rather than teaching the engine the
    pack's phrasing keeps the matcher a single loop with no special cases,
    and keeps a pack author from ever writing a glob.
    """
    if not spec:
        return []
    if not isinstance(spec, dict):
        raise ValueError(
            "trust/source_tiers.yaml must be a mapping with `domains`, "
            "`rules`, `default` and `tiers` keys; got "
            f"{type(spec).__name__}. Building on regardless would ship a pack "
            "whose sources all fall through to the unknown default, which is "
            "invisible until someone wonders why a manufacturer bulletin "
            "ranks below a forum thread."
        )

    rows: list[tuple[str, str, str]] = []
    for domain, body in (spec.get("domains") or {}).items():
        body = body or {}
        rows.append(
            (str(domain).casefold(), body.get("tier", ""), body.get("note", ""))
        )

    for rule in spec.get("rules") or []:
        for fragment in rule.get("domain_contains") or []:
            rows.append(
                (
                    f"*{str(fragment).casefold()}*",
                    rule.get("tier", ""),
                    rule.get("note", ""),
                )
            )

    if spec.get("default"):
        rows.append(("*", str(spec["default"]), "pack default"))

    return [r for r in rows if r[1]]


def _tier_trust_rows(spec) -> list[tuple[str, float]]:
    """What each tier is worth, per the pack that named it.

    A pack may invent a tier the engine has no default weight for; without
    this every claim behind it would quietly fall to the unknown default and
    the pack author would never learn why.
    """
    if not isinstance(spec, dict):
        return []  # already reported by _tier_rows
    out = []
    for tier, body in (spec.get("tiers") or {}).items():
        trust = (body or {}).get("trust")
        if trust is not None:
            out.append((str(tier), float(trust)))
    return out


def _emit_terms(conn, pack_id, terms, row_ids: list[str]) -> None:
    for t in terms:
        conn.execute(
            "INSERT OR REPLACE INTO terms (term_id, pack_id, role, datatype,"
            " unit, parent_id, label_json, match_json) VALUES (?,?,?,?,?,?,?,?)",
            (
                t["term_id"],
                pack_id,
                t.get("role", "attribute"),
                t.get("datatype", "text"),
                t.get("unit", ""),
                t.get("parent", ""),
                yaml.safe_dump(t.get("label", {}), allow_unicode=True),
                yaml.safe_dump(t.get("match", {}), allow_unicode=True),
            ),
        )
        row_ids.append(f"term:{t['term_id']}")
        for alias in t.get("aliases", []) or []:
            conn.execute(
                "INSERT OR IGNORE INTO term_aliases VALUES (?,?,?,?)",
                (t["term_id"], pack_id, alias, ""),
            )
            row_ids.append(f"term_alias:{t['term_id']}:{alias}")


def _emit_subjects(
    conn, pack_id, subjects, man, term_by_id, row_ids: list[str]
) -> dict[tuple[str, str], str]:
    def numeric(key, value):
        """value_num is set for declared-numeric terms so ranges stay indexable."""
        if term_by_id.get(key, {}).get("datatype") in _NUMERIC_TYPES:
            return _as_number(value)
        return None

    known: dict[tuple[str, str], str] = {}
    for entry in subjects:
        kind, subject_id = _subject_key(entry, man.identity_keys)
        known[(kind, subject_id)] = subject_id
        conn.execute(
            "INSERT OR IGNORE INTO subjects VALUES (?,?,?,?)",
            (subject_id, pack_id, kind, entry.get("label", "")),
        )
        row_ids.append(subject_id)

        identity = entry.get("identity") or {}
        declared = set(man.identity_keys[kind])
        # A spec is a bare value or `{value, source}`; the source is the page it
        # was read from (B173). Identity keys carry none.
        sources: dict[str, str] = {}
        specs: dict = {}
        for key, raw in (entry.get("attributes") or {}).items():
            if isinstance(raw, dict):
                sources[key] = str(raw.get("source") or "").strip()
                raw = raw.get("value")
            specs[key] = raw
        merged = {**identity, **specs}
        for key, value in merged.items():
            if key not in term_by_id:
                raise ValueError(
                    f"subject {entry.get('label', subject_id)!r} uses "
                    f"undeclared term {key!r} — add it to vocabulary/terms.yaml"
                )
            attribute_id = ids.attribute_id(subject_id, key, value)
            conn.execute(
                "INSERT OR IGNORE INTO attributes (attribute_id, pack_id,"
                " subject_id, key, value_text, value_num, unit, valid_from,"
                " valid_to, is_identity, confidence, source_url)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    attribute_id,
                    pack_id,
                    subject_id,
                    key,
                    str(value),
                    numeric(key, value),
                    term_by_id[key].get("unit", ""),
                    "",
                    "",
                    1 if key in declared else 0,
                    None,
                    sources.get(key, ""),
                ),
            )
            row_ids.append(attribute_id)

        for alias in entry.get("aliases", []) or []:
            conn.execute(
                "INSERT OR IGNORE INTO subject_aliases VALUES (?,?,?,?,?)",
                (subject_id, pack_id, alias, "", "attribution_safe"),
            )
            row_ids.append(f"subject_alias:{subject_id}:{alias}")

    return known


def _emit_relations(conn, pack_id, subjects, man, known, row_ids: list[str]) -> None:
    # Relations resolve after every subject exists, so an edge may point
    # forward to a subject declared later in the file.
    for entry in subjects:
        _, subject_id = _subject_key(entry, man.identity_keys)
        for rel in entry.get("relations", []) or []:
            target_kind, target_id = _subject_key(rel["object"], man.identity_keys)
            if (target_kind, target_id) not in known:
                raise ValueError(
                    f"relation from {entry.get('label')!r} points at unknown "
                    f"subject {rel['object']!r}"
                )
            relation_id = ids.relation_id(subject_id, rel["predicate"], target_id)
            conn.execute(
                "INSERT OR IGNORE INTO relations VALUES (?,?,?,?,?,?)",
                (
                    relation_id,
                    pack_id,
                    subject_id,
                    rel["predicate"],
                    target_id,
                    rel.get("note", ""),
                ),
            )
            row_ids.append(relation_id)


def _emit_claim_row(conn, pack_id, entry, man, known, row_ids: list[str]) -> str:
    kind, subject_id = _subject_key(entry["subject"], man.identity_keys)
    if (kind, subject_id) not in known:
        raise ValueError(
            f"claim {entry.get('text', {}).get('en', {}).get('title', '?')!r} "
            f"points at unknown subject {entry['subject']!r}"
        )

    texts = entry.get("text") or {}
    primary: dict = texts.get("en") or next(iter(texts.values()), {})
    claim_id = ids.claim_id(
        subject_id, entry["kind"], entry["domain"], primary.get("title", "")
    )
    conn.execute(
        "INSERT OR IGNORE INTO claims (claim_id, pack_id, subject_id,"
        " kind, domain, severity, consequence, detection, component,"
        " subsystem, author_confidence, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            claim_id,
            pack_id,
            subject_id,
            entry["kind"],
            entry["domain"],
            entry.get("severity", "medium"),
            entry.get("consequence", ""),
            entry.get("detection", ""),
            entry.get("component", ""),
            entry.get("subsystem", ""),
            entry.get("confidence"),
            _now(),
        ),
    )
    row_ids.append(claim_id)
    return claim_id


def _emit_claim_text(conn, pack_id, claim_id, entry, row_ids: list[str]) -> None:
    texts = entry.get("text") or {}
    for lang, block in texts.items():
        conn.execute(
            "INSERT OR IGNORE INTO claim_text VALUES (?,?,?,?,?,?)",
            (
                claim_id,
                pack_id,
                lang,
                block.get("title", ""),
                block.get("body", ""),
                block.get("advice", ""),
            ),
        )
        row_ids.append(f"text:{claim_id}:{lang}")


def _emit_claim_conditions(conn, pack_id, claim_id, entry, row_ids: list[str]) -> None:
    for seq, cond in enumerate(entry.get("conditions", []) or []):
        conn.execute(
            "INSERT OR REPLACE INTO claim_conditions (claim_id, pack_id,"
            " seq, key, op, value_text, value_num, on_missing, weight)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (
                claim_id,
                pack_id,
                seq,
                cond["key"],
                cond["op"],
                str(cond.get("value", "")),
                _as_number(cond.get("value")),
                cond.get("on_missing", "open"),
                float(cond.get("weight", 1.0)),
            ),
        )
        row_ids.append(f"cond:{claim_id}:{seq}")


def _emit_claim_evidence(conn, pack_id, claim_id, entry, row_ids: list[str]) -> None:
    for ev in entry.get("evidence", []) or []:
        url = ev.get("url") or ev.get("source_url") or ""
        source_id = ids.source_id(url=url, text=ev.get("quote", ""))
        conn.execute(
            "INSERT OR IGNORE INTO sources (source_id, pack_id, url,"
            " domain, site_or_channel, title, lang, source_type,"
            " published_at, retrieved_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                source_id,
                pack_id,
                url,
                _domain_of(url),
                ev.get("site", ""),
                ev.get("source_title", ""),
                ev.get("lang", ""),
                ev.get("source_type", "page"),
                ev.get("published_at", ""),
                ev.get("retrieved_at", ""),
            ),
        )
        row_ids.append(source_id)

        evidence_id = ids.evidence_id(source_id, ev.get("quote", ""))
        conn.execute(
            "INSERT OR IGNORE INTO evidence (evidence_id, pack_id,"
            " claim_id, source_id, quote, locator, stance, independent)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (
                evidence_id,
                pack_id,
                claim_id,
                source_id,
                ev.get("quote", ""),
                ev.get("locator", ""),
                ev.get("stance", "supports"),
                1 if ev.get("independent", True) else 0,
            ),
        )
        row_ids.append(evidence_id)


def _emit_claims(conn, pack_id, claims, man, known, row_ids: list[str]) -> None:
    for entry in claims:
        claim_id = _emit_claim_row(conn, pack_id, entry, man, known, row_ids)
        _emit_claim_text(conn, pack_id, claim_id, entry, row_ids)
        _emit_claim_conditions(conn, pack_id, claim_id, entry, row_ids)
        _emit_claim_evidence(conn, pack_id, claim_id, entry, row_ids)


def _emit_pack_assets(conn, pack_id, root, row_ids: list[str]) -> None:
    # Non-tabular assets: whatever the pack ships that is text rather than
    # rows. Read in sorted order so the digest is stable.
    for name, kind in (
        ("research/principle.md", "principle"),
        ("research/templates.yaml", "templates"),
        ("research/skill.md", "skill"),
    ):
        path = root / name
        if path.exists():
            conn.execute(
                "INSERT OR REPLACE INTO pack_assets VALUES (?,?,?,?)",
                (pack_id, name, kind, path.read_text(encoding="utf-8")),
            )
            row_ids.append(f"asset:{name}")

    for path in sorted((root / "adapters").glob("*.json")):
        conn.execute(
            "INSERT OR REPLACE INTO pack_assets VALUES (?,?,?,?)",
            (
                pack_id,
                f"adapters/{path.name}",
                "adapter",
                path.read_text(encoding="utf-8"),
            ),
        )
        row_ids.append(f"asset:adapters/{path.name}")


def _emit_trust_and_gates(conn, pack_id, root, row_ids: list[str]) -> None:
    for pattern, tier, note in _tier_rows(
        _load_yaml(root / "trust" / "source_tiers.yaml", {})
    ):
        conn.execute(
            "INSERT OR REPLACE INTO source_tiers VALUES (?,?,?,?)",
            (pattern, pack_id, tier, note),
        )
        row_ids.append(f"tier:{pattern}")

    for kind, pattern, note in _gate_rows(
        _load_yaml(root / "vocabulary" / "gates.yaml", {})
    ):
        conn.execute(
            "INSERT OR REPLACE INTO gate_terms VALUES (?,?,?,?)",
            (pack_id, kind, pattern, note),
        )
        row_ids.append(f"gate:{kind}:{pattern}")

    for tier, trust in _tier_trust_rows(
        _load_yaml(root / "trust" / "source_tiers.yaml", {})
    ):
        conn.execute(
            "INSERT OR REPLACE INTO tier_trust VALUES (?,?,?)",
            (tier, pack_id, trust),
        )
        row_ids.append(f"tier_trust:{tier}")


def _write_manifest_row(conn, pack_id, man, row_ids: list[str]) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO packs (pack_id, name, version, schema_version,"
        " built_at, publisher, license, origin_url, content_digest,"
        " manifest_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            pack_id,
            man.name,
            man.version,
            SCHEMA_VERSION,
            _now(),
            man.publisher,
            man.license,
            man.origin_url,
            ids.content_digest(row_ids, man.raw),
            yaml.safe_dump(man.raw, allow_unicode=True),
        ),
    )


def build(root, out_path) -> Path:
    """Build `root` into a pack file at `out_path`. Returns the path."""
    root = Path(root)
    out_path = Path(out_path)
    man = load_manifest(root)

    terms = _load_yaml(man.vocabulary_dir / "terms.yaml", [])
    subjects = _load_yaml(man.data_dir / "subjects.yaml", [])
    claims = _load_yaml(man.data_dir / "claims.yaml", [])

    term_by_id = {t["term_id"]: t for t in terms}

    if out_path.exists():
        out_path.unlink()
    conn = connect(out_path)
    pack_id = man.pack_id
    row_ids: list[str] = []

    with conn:
        _emit_terms(conn, pack_id, terms, row_ids)
        known = _emit_subjects(conn, pack_id, subjects, man, term_by_id, row_ids)
        _emit_relations(conn, pack_id, subjects, man, known, row_ids)
        _emit_claims(conn, pack_id, claims, man, known, row_ids)
        _emit_pack_assets(conn, pack_id, root, row_ids)
        _emit_trust_and_gates(conn, pack_id, root, row_ids)
        _write_manifest_row(conn, pack_id, man, row_ids)

    conn.close()
    return out_path


def digest_of(pack_path) -> str:
    """The pack's content digest, as recorded at build time."""
    conn = connect(pack_path, read_only=True)
    try:
        return conn.execute("SELECT content_digest FROM packs").fetchone()[0]
    finally:
        conn.close()
