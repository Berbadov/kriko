"""Building a pack directory into a distributable pack file.

Authoring a pack must be a data-only act: YAML in, SQLite out, no Python. That
is the scalability principle from CLAUDE.md applied to the pivot — if adding a
product category needs code, the category will not get added.
"""

import textwrap

import pytest

from kriko.pack import build, manifest
from kriko.store import ids, packstore
from kriko.store.db import connect

PACK_TOML = """
[pack]
id = "org.kriko.drill"
name = "Cordless drills"
version = "0.1.0"
license = "CC-BY-SA-4.0"
publisher = "kriko"

[identity]
product = ["brand", "model"]
"""

TERMS = """
- term_id: brand
  role: attribute
  datatype: text
  label: {en: Brand}
  match: {required: true}
- term_id: model
  role: attribute
  datatype: text
  match: {required: true}
- term_id: voltage_v
  role: attribute
  datatype: number
  unit: v
- term_id: usage_hours
  role: context_key
  datatype: number
  unit: hours
- term_id: mechanical
  role: domain
- term_id: product
  role: subject_kind
"""

SUBJECTS = """
- kind: product
  label: Makita DHP484 18V brushless drill
  identity: {brand: makita, model: DHP484}
  attributes: {voltage_v: 18}
"""

CLAIMS = """
- subject: {kind: product, identity: {brand: makita, model: DHP484}}
  kind: known_issue
  domain: mechanical
  severity: high
  text:
    en:
      title: Chuck jaws slip under high torque after heavy use
      body: The keyless chuck loses grip on round shanks once worn.
      advice: Clamp a drill bit and try to twist it by hand.
  conditions:
    - {key: usage_hours, op: gte, value: 500, on_missing: open, weight: 0.7}
  evidence:
    - url: https://example.com/drill-review
      quote: After about two years of daily use the chuck would not hold a bit.
"""


def _write(tmp_path, *, toml=PACK_TOML, terms=TERMS, subjects=SUBJECTS, claims=CLAIMS):
    root = tmp_path / "drill"
    (root / "vocabulary").mkdir(parents=True)
    (root / "data").mkdir(parents=True)
    (root / "pack.toml").write_text(textwrap.dedent(toml), encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(terms, encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text(subjects, encoding="utf-8")
    (root / "data" / "claims.yaml").write_text(claims, encoding="utf-8")
    return root


def test_manifest_reads_identity_keys(tmp_path):
    m = manifest.load(_write(tmp_path))
    assert m.pack_id == "org.kriko.drill"
    assert m.version == "0.1.0"
    assert m.identity_keys["product"] == ["brand", "model"]


def test_manifest_rejects_a_missing_id(tmp_path):
    root = _write(tmp_path, toml='[pack]\nname = "x"\nversion = "0.1.0"\n')
    with pytest.raises(ValueError, match="id"):
        manifest.load(root)


def test_manifest_rejects_a_pack_with_no_identity_keys(tmp_path):
    """Without identity keys every subject of a kind would hash together."""
    root = _write(
        tmp_path,
        toml=PACK_TOML.replace(
            '[identity]\nproduct = ["brand", "model"]', "[identity]"
        ),
    )
    with pytest.raises(ValueError, match="identity"):
        manifest.load(root)


def test_build_emits_exactly_one_pack_row(tmp_path):
    out = build.build(_write(tmp_path), tmp_path / "drill.kpack")
    conn = connect(out)
    rows = list(conn.execute("SELECT pack_id, name, version FROM packs"))
    assert len(rows) == 1
    assert rows[0]["pack_id"] == "org.kriko.drill"
    conn.close()


def test_build_is_deterministic(tmp_path):
    """Two builds of identical data must produce the same digest.

    The digest is over sorted row ids, never over the file bytes — zipfile bakes
    in mtimes and entry ordering, so a byte checksum would differ on every build
    and registry verification would reject honest packs.
    """
    root = _write(tmp_path)
    a = build.build(root, tmp_path / "a.kpack")
    b = build.build(root, tmp_path / "b.kpack")
    assert build.digest_of(a) == build.digest_of(b)


def test_digest_changes_when_data_changes(tmp_path):
    root = _write(tmp_path)
    before = build.digest_of(build.build(root, tmp_path / "a.kpack"))
    (root / "data" / "subjects.yaml").write_text(
        SUBJECTS.replace("voltage_v: 18", "voltage_v: 36"), encoding="utf-8"
    )
    after = build.digest_of(build.build(root, tmp_path / "b.kpack"))
    assert before != after


def test_subject_ids_match_the_shared_hash(tmp_path):
    """The builder must not invent its own identity scheme."""
    out = build.build(_write(tmp_path), tmp_path / "drill.kpack")
    conn = connect(out)
    (row,) = conn.execute("SELECT subject_id FROM subjects")
    assert row["subject_id"] == ids.subject_id(
        "product", {"brand": "makita", "model": "DHP484"}
    )
    conn.close()


def test_identity_attributes_are_marked_and_stored(tmp_path):
    out = build.build(_write(tmp_path), tmp_path / "drill.kpack")
    conn = connect(out)
    got = {
        r["key"]: (r["value_text"], r["is_identity"])
        for r in conn.execute("SELECT key, value_text, is_identity FROM attributes")
    }
    assert got["brand"] == ("makita", 1)
    assert got["model"] == ("DHP484", 1)
    assert got["voltage_v"] == ("18", 0)
    conn.close()


def test_numeric_attributes_get_value_num_for_range_queries(tmp_path):
    out = build.build(_write(tmp_path), tmp_path / "drill.kpack")
    conn = connect(out)
    (row,) = conn.execute("SELECT value_num FROM attributes WHERE key = 'voltage_v'")
    assert row["value_num"] == 18.0
    conn.close()


def test_a_product_with_no_relations_builds(tmp_path):
    """The drill is the degenerate case: zero components, and that is fine."""
    out = build.build(_write(tmp_path), tmp_path / "drill.kpack")
    conn = connect(out)
    assert conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 1
    conn.close()


def test_claim_text_conditions_and_evidence_land(tmp_path):
    out = build.build(_write(tmp_path), tmp_path / "drill.kpack")
    conn = connect(out)
    (text,) = conn.execute("SELECT lang, title FROM claim_text")
    assert text["lang"] == "en"
    assert text["title"].startswith("Chuck jaws slip")

    (cond,) = conn.execute(
        "SELECT key, op, value_num, on_missing, weight FROM claim_conditions"
    )
    assert (cond["key"], cond["op"], cond["value_num"]) == ("usage_hours", "gte", 500.0)
    assert cond["on_missing"] == "open"

    (ev,) = conn.execute("SELECT quote, stance FROM evidence")
    assert ev["stance"] == "supports"
    (src,) = conn.execute("SELECT domain FROM sources")
    assert src["domain"] == "example.com"
    conn.close()


def test_a_sources_retrieval_date_survives_the_build(tmp_path):
    """`retrieved_at` in the YAML must reach sources.retrieved_at."""
    claims = CLAIMS.replace(
        "quote: After about two years of daily use the chuck would not hold a bit.",
        "quote: After about two years of daily use the chuck would not hold a bit.\n"
        "      retrieved_at: \"2026-08-01\"",
    )
    out = build.build(_write(tmp_path, claims=claims), tmp_path / "drill.kpack")
    conn = connect(out)
    (retrieved_at,) = conn.execute("SELECT retrieved_at FROM sources")
    assert retrieved_at["retrieved_at"] == "2026-08-01"
    conn.close()


def test_build_rejects_a_claim_pointing_at_an_unknown_subject(tmp_path):
    """A dangling reference must fail the build, not ship a claim nobody sees."""
    root = _write(tmp_path, claims=CLAIMS.replace("DHP484", "GHOST999"))
    with pytest.raises(ValueError, match="unknown subject"):
        build.build(root, tmp_path / "drill.kpack")


def test_build_rejects_an_attribute_with_no_declared_term(tmp_path):
    """Vocabulary is data, but it is still required — typos become new keys."""
    root = _write(tmp_path, subjects=SUBJECTS.replace("voltage_v", "voltaje_v"))
    with pytest.raises(ValueError, match="undeclared term"):
        build.build(root, tmp_path / "drill.kpack")


def test_built_pack_installs_and_answers(tmp_path):
    """The round trip that matters: build -> install -> the rows are queryable."""
    out = build.build(_write(tmp_path), tmp_path / "drill.kpack")
    store = connect(tmp_path / "store.sqlite")
    pack_id = packstore.install(store, out)

    assert pack_id == "org.kriko.drill"
    (title,) = store.execute(
        "SELECT ct.title FROM claim_text ct"
        " JOIN claims c USING (claim_id, pack_id)"
        " JOIN subjects s USING (subject_id, pack_id)"
        " JOIN packs p USING (pack_id)"
        " WHERE p.enabled = 1 AND s.label LIKE 'Makita%'"
    ).fetchone()
    assert title.startswith("Chuck jaws slip")
    store.close()


GATES_YAML = """
covered:
  - {pattern: brake pad, note: the inspector measures pad thickness}
generic:
  - wear and tear is normal
noise:
  - {pattern: "\\\\bwarning\\\\s+light\\\\b", note: true of every car}
"""


def test_gate_vocabulary_ships_as_rows(tmp_path):
    root = _write(tmp_path)
    (root / "vocabulary" / "gates.yaml").write_text(GATES_YAML, encoding="utf-8")
    out = build.build(root, tmp_path / "p.kpack")
    conn = connect(out)
    rows = {
        (r["kind"], r["pattern"])
        for r in conn.execute("SELECT kind, pattern FROM gate_terms")
    }
    assert ("covered", "brake pad") in rows
    assert ("generic", "wear and tear is normal") in rows
    note = conn.execute(
        "SELECT note FROM gate_terms WHERE pattern = 'brake pad'"
    ).fetchone()["note"]
    assert "pad thickness" in note
    conn.close()


def test_an_unknown_gate_kind_fails_the_build(tmp_path):
    root = _write(tmp_path)
    (root / "vocabulary" / "gates.yaml").write_text(
        "coverd:\n  - brake pad\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="unknown rule kinds"):
        build.build(root, tmp_path / "p.kpack")


# ── trust ────────────────────────────────────────────────────────────────
#
# A pack says how much it trusts a source in two halves: which tier a domain
# belongs to, and what a tier is worth. Both are pack data — the reader's own
# rows win over them, and nothing here is an engine constant.

TIERS_YAML = """
tiers:
  authoritative: {trust: 1.0}
  forum_ugc:     {trust: 0.4}
  seo_blog:      {trust: 0.2}

default: seo_blog

domains:
  maker.example: {tier: authoritative, note: manufacturer docs}
  another.example: {tier: authoritative}

rules:
  - tier: forum_ugc
    domain_contains: ["forum.", "kulubu"]
"""


def _pack_with_tiers(tmp_path, yaml_text):
    root = _write(tmp_path)
    (root / "trust").mkdir(exist_ok=True)
    (root / "trust" / "source_tiers.yaml").write_text(yaml_text, encoding="utf-8")
    return root


def test_a_domain_is_filed_under_the_tier_the_pack_gave_it(tmp_path):
    from kriko.store.db import connect

    out = build.build(_pack_with_tiers(tmp_path, TIERS_YAML), tmp_path / "p.kpack")
    conn = connect(out)
    rows = dict(
        conn.execute("SELECT domain_pattern, tier FROM source_tiers").fetchall()
    )
    assert rows["maker.example"] == "authoritative"
    conn.close()


def test_a_contains_rule_becomes_the_wildcard_the_engine_understands(tmp_path):
    """ "Anything with 'forum.' in it is user-generated", without listing the
    internet. `tier_of` already reads `*substring*`; the builder's job is only
    to write the pack's phrasing into it."""
    from kriko.store.db import connect

    out = build.build(_pack_with_tiers(tmp_path, TIERS_YAML), tmp_path / "p.kpack")
    conn = connect(out)
    rows = dict(
        conn.execute("SELECT domain_pattern, tier FROM source_tiers").fetchall()
    )
    assert rows["*forum.*"] == "forum_ugc"
    assert rows["*kulubu*"] == "forum_ugc"
    conn.close()


def test_the_default_tier_is_stored_as_the_catch_all_pattern(tmp_path):
    from kriko.store.db import connect

    out = build.build(_pack_with_tiers(tmp_path, TIERS_YAML), tmp_path / "p.kpack")
    conn = connect(out)
    rows = dict(
        conn.execute("SELECT domain_pattern, tier FROM source_tiers").fetchall()
    )
    assert rows["*"] == "seo_blog"
    conn.close()


def test_what_a_tier_is_worth_ships_with_the_pack_that_named_it(tmp_path):
    """Otherwise a pack could invent a tier the engine has no weight for, and
    every claim behind it would silently fall to the unknown default."""
    from kriko.store.db import connect

    out = build.build(_pack_with_tiers(tmp_path, TIERS_YAML), tmp_path / "p.kpack")
    conn = connect(out)
    rows = dict(conn.execute("SELECT tier, trust FROM tier_trust").fetchall())
    assert rows == {"authoritative": 1.0, "forum_ugc": 0.4, "seo_blog": 0.2}
    conn.close()


def test_a_pack_with_no_trust_file_still_builds(tmp_path):
    """Trust is optional. A pack that says nothing about sources gets the
    engine's defaults rather than a build error."""
    out = build.build(_write(tmp_path), tmp_path / "p.kpack")
    assert out.exists()


def test_a_trust_file_the_builder_cannot_read_fails_the_build(tmp_path):
    """Loudly, rather than by shipping a pack with no tiers in it.

    The silent version of this cost a commit: `packs/cars` moved its trust
    file in from the old tree unchanged, the builder read a shape it did not
    understand, and the pack built successfully with every source falling
    through to the unknown default. A build error is recoverable in seconds;
    a pack that quietly stopped trusting its manufacturer sources is not
    visible at all.
    """
    root = _pack_with_tiers(tmp_path, "- {domain: a.example, tier: specialist}\n")
    with pytest.raises(ValueError, match="source_tiers.yaml"):
        build.build(root, tmp_path / "p.kpack")
