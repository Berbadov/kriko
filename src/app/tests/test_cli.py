"""The command line — the reader's whole loop, with no server involved.

The interesting tests here are the two-pack ones. A single installed pack
exercises nothing that a library test does not already cover; two packs from
different authors, with colliding vocabularies, is where this design either
works or does not.
"""

import textwrap

import pytest

from app.cli import main
from kriko.pack import build

DRILLISH = {
    "toml": """
        [pack]
        id = "tools"
        name = "Tools"
        version = "0.1.0"
        [identity]
        product = ["brand", "model"]
    """,
    "terms": """
        - {term_id: product, role: subject_kind}
        # NOTE the alias: this pack calls it `brand` and accepts `make`.
        - {term_id: brand, role: attribute, datatype: text, aliases: [make],
           match: {required: true}}
        - {term_id: model, role: attribute, datatype: text, match: {required: true}}
        - {term_id: usage_hours, role: context_key, datatype: number, unit: hours}
        - {term_id: mech, role: domain}
    """,
    "subjects": """
        - kind: product
          label: Makita DHP484
          identity: {brand: makita, model: DHP484}
    """,
    "claims": """
        - subject: {kind: product, identity: {brand: makita, model: DHP484}}
          kind: known_issue
          domain: mech
          severity: high
          text: {en: {title: Chuck slips under torque, body: b, advice: a}}
          conditions:
            - {key: usage_hours, op: gte, value: 400, on_missing: open, weight: 0.7}
    """,
}

CARISH = {
    "toml": """
        [pack]
        id = "autos"
        name = "Autos"
        version = "0.1.0"
        [identity]
        product = ["make", "model"]
    """,
    "terms": """
        - {term_id: product, role: subject_kind}
        # ...and this pack does the exact opposite. Merging the two alias tables
        # globally makes one of them unreachable.
        - {term_id: make, role: attribute, datatype: text, aliases: [brand],
           match: {required: true}}
        - {term_id: model, role: attribute, datatype: text, match: {required: true}}
        - {term_id: usage_km, role: context_key, datatype: number, unit: km}
        - {term_id: engine, role: domain}
    """,
    "subjects": """
        - kind: product
          label: Renault Megane
          identity: {make: renault, model: megane}
    """,
    "claims": """
        - subject: {kind: product, identity: {make: renault, model: megane}}
          kind: known_issue
          domain: engine
          severity: high
          text: {en: {title: Injector fouling at high mileage, body: b, advice: a}}
          conditions:
            - {key: usage_km, op: gte, value: 120000, on_missing: open, weight: 0.7}
    """,
}


def _pack(tmp_path, name, spec):
    root = tmp_path / name
    (root / "vocabulary").mkdir(parents=True)
    (root / "data").mkdir(parents=True)
    (root / "pack.toml").write_text(textwrap.dedent(spec["toml"]), encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(
        textwrap.dedent(spec["terms"]), encoding="utf-8"
    )
    (root / "data" / "subjects.yaml").write_text(
        textwrap.dedent(spec["subjects"]), encoding="utf-8"
    )
    (root / "data" / "claims.yaml").write_text(
        textwrap.dedent(spec["claims"]), encoding="utf-8"
    )
    return build.build(root, tmp_path / f"{name}.kpack")


@pytest.fixture
def store_path(tmp_path):
    return str(tmp_path / "store.sqlite")


@pytest.fixture
def both(tmp_path, store_path):
    for name, spec in (("tools", DRILLISH), ("autos", CARISH)):
        assert (
            main(["--store", store_path, "install", str(_pack(tmp_path, name, spec))])
            == 0
        )
    return store_path


def _run(capsys, *argv):
    code = main(list(argv))
    return code, capsys.readouterr().out


def test_install_reports_what_arrived(tmp_path, store_path, capsys):
    pack = _pack(tmp_path, "tools", DRILLISH)
    code, out = _run(capsys, "--store", store_path, "install", str(pack))
    assert code == 0
    assert "installed tools" in out
    assert "1 claims" in out


def test_packs_lists_both_with_their_state(both, capsys):
    code, out = _run(capsys, "--store", both, "packs")
    assert code == 0
    assert "tools" in out and "autos" in out
    assert out.count("enabled") == 2


def test_each_pack_answers_in_its_own_words(both, capsys):
    """The collision that broke the first two-pack query.

    `brand` is an alias of `make` in one pack and a real term in the other. A
    single merged alias table makes them fight and one pack goes silent — with
    both installed, the first query returned nothing at all for either.
    """
    _, drill = _run(
        capsys,
        "--store",
        both,
        "lookup",
        "brand=makita",
        "model=DHP484",
        "--ctx",
        "usage_hours=800",
    )
    assert "Chuck slips under torque" in drill

    _, car = _run(
        capsys,
        "--store",
        both,
        "lookup",
        "make=renault",
        "model=megane",
        "--ctx",
        "usage_km=180000",
    )
    assert "Injector fouling at high mileage" in car


def test_a_query_for_one_pack_does_not_return_the_other(both, capsys):
    _, out = _run(
        capsys,
        "--store",
        both,
        "lookup",
        "brand=makita",
        "model=DHP484",
        "--ctx",
        "usage_hours=800",
    )
    assert "Injector fouling" not in out


def test_an_unknown_product_says_so_without_failing(both, capsys):
    code, out = _run(capsys, "--store", both, "lookup", "brand=nobody", "model=nothing")
    assert code == 0
    assert "no_match" in out
    assert "no claims" in out


def test_disable_hides_a_pack_and_enable_brings_it_back(both, capsys):
    _run(capsys, "--store", both, "enable", "tools", "--disable")
    _, hidden = _run(
        capsys,
        "--store",
        both,
        "lookup",
        "brand=makita",
        "model=DHP484",
        "--ctx",
        "usage_hours=800",
    )
    assert "Chuck slips" not in hidden

    _run(capsys, "--store", both, "enable", "tools")
    _, back = _run(
        capsys,
        "--store",
        both,
        "lookup",
        "brand=makita",
        "model=DHP484",
        "--ctx",
        "usage_hours=800",
    )
    assert "Chuck slips" in back


def test_uninstall_leaves_the_other_pack_answering(both, capsys):
    _run(capsys, "--store", both, "uninstall", "tools")
    _, out = _run(
        capsys,
        "--store",
        both,
        "lookup",
        "make=renault",
        "model=megane",
        "--ctx",
        "usage_km=180000",
    )
    assert "Injector fouling" in out


def test_uninstalling_something_absent_is_an_error_not_a_crash(both, capsys):
    assert main(["--store", both, "uninstall", "nope"]) == 1


def test_verbose_explains_the_ranking_and_shows_sources(both, capsys):
    _, out = _run(
        capsys,
        "--store",
        both,
        "lookup",
        "brand=makita",
        "model=DHP484",
        "--ctx",
        "usage_hours=800",
        "-v",
    )
    assert "high severity" in out
    assert "from pack: tools" in out


def test_an_unstated_context_value_is_reported_as_the_reason(both, capsys):
    """Fail-open, visible at the command line: shown, and told why it ranked low."""
    _, out = _run(
        capsys, "--store", both, "lookup", "brand=makita", "model=DHP484", "-v"
    )
    assert "Chuck slips under torque" in out
    assert "usage_hours not stated" in out


def test_a_bad_argument_is_rejected_clearly(store_path):
    with pytest.raises(SystemExit, match="key=value"):
        main(["--store", store_path, "lookup", "brandmakita"])


def test_build_prefers_a_packs_own_builder(tmp_path, capsys):
    """cars ships build.py because its data needs generating, not transcribing.

    Pointing the generic builder at it "succeeds" and produces a pack with
    vocabulary and nothing else — 46 terms, 0 claims. This is the bug: `kriko
    build packs/cars` must run cars' own build.py, not the generic one.
    """
    out = tmp_path / "cars.kpack"
    code, output = _run(
        capsys, "--store", str(tmp_path / "store.sqlite"), "build", "packs/cars", "--out", str(out)
    )
    assert code == 0
    assert out.exists()

    from kriko.store.db import connect

    conn = connect(out)
    try:
        claims = conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
        subjects = conn.execute("SELECT COUNT(*) FROM subjects").fetchone()[0]
    finally:
        conn.close()

    assert claims > 100, f"expected cars' own builder to run, got {claims} claims"
    assert subjects > 0
    assert f"{claims} claims" in output


def test_build_still_works_for_a_pack_with_no_builder_of_its_own(tmp_path, capsys):
    """packs/drill has no build.py — the generic path must still work for it."""
    out = tmp_path / "drill.kpack"
    code, output = _run(
        capsys, "--store", str(tmp_path / "store.sqlite"), "build", "packs/drill", "--out", str(out)
    )
    assert code == 0
    assert out.exists()
    assert "claims" in output


def test_build_refuses_an_empty_pack_without_force(tmp_path, capsys):
    """A pack with vocabulary and no knowledge cannot answer anything.

    `install` accepts it cheerfully, so `build` is where the emptiness has to
    be caught — refuse to write it, unless the author passes --force because
    an empty pack is a legitimate intermediate state while authoring one.
    """
    root = tmp_path / "empty"
    (root / "vocabulary").mkdir(parents=True)
    (root / "data").mkdir(parents=True)
    (root / "pack.toml").write_text(
        textwrap.dedent(
            """
            [pack]
            id = "empty"
            name = "Empty"
            version = "0.1.0"
            [identity]
            product = ["brand", "model"]
            """
        ),
        encoding="utf-8",
    )
    (root / "vocabulary" / "terms.yaml").write_text(
        textwrap.dedent(
            """
            - {term_id: product, role: subject_kind}
            - {term_id: brand, role: attribute, datatype: text, match: {required: true}}
            - {term_id: model, role: attribute, datatype: text, match: {required: true}}
            """
        ),
        encoding="utf-8",
    )
    (root / "data" / "subjects.yaml").write_text("", encoding="utf-8")
    (root / "data" / "claims.yaml").write_text("", encoding="utf-8")

    out = tmp_path / "empty.kpack"

    code, _ = _run(
        capsys, "--store", str(tmp_path / "store.sqlite"), "build", str(root), "--out", str(out)
    )
    assert code == 1
    assert not out.exists()

    code, output = _run(
        capsys,
        "--store", str(tmp_path / "store.sqlite"),
        "build", str(root), "--out", str(out), "--force",
    )
    assert code == 0
    assert out.exists()
    assert "0 subjects" in output


# ── the engine-backed subcommands: prefs, costs, sites, verify, drafts,
# operations. Each attaches to a running engine or starts one of its own
# (`app.tui.client.connect`), against `--store`'s own sibling `app.sqlite` —
# never the reader's real `~/.kriko`.

def test_prefs_shows_what_the_machine_offers_with_no_engine_running(store_path, capsys):
    """The defect this closes: before this command existed, the only way to
    see or change the preferred harness/model/search provider was the web
    dashboard — invisible when the window will not open."""
    code, out = _run(capsys, "--store", store_path, "prefs")
    assert code == 0
    assert "chosen now" in out


def test_prefs_can_set_a_value_and_read_it_back(store_path, capsys):
    code, _ = _run(capsys, "--store", store_path, "prefs", "--model", "gpt-4o")
    assert code == 0
    _, out = _run(capsys, "--store", store_path, "prefs")
    assert "gpt-4o" in out


def test_setting_one_preference_does_not_reset_the_others(store_path, capsys):
    """The defect: `prefs --model X` sent `preferred_harness=""` and
    `search_provider=""` along with it — every field the CLI parser has a
    default for, not only the one the reader actually asked to change — and
    `/api/prefs` writes any field present in the request body, so a harness
    chosen earlier was silently reset to "whatever the machine offers" the
    next time the reader only meant to change the model. Rule 6: a command
    run twice with different flags must not clobber what the first run set."""
    _run(capsys, "--store", store_path, "prefs", "--harness", "claude-code")
    _run(capsys, "--store", store_path, "prefs", "--model", "gpt-4o")
    _, out = _run(capsys, "--store", store_path, "prefs")
    assert "claude-code" in out
    assert "gpt-4o" in out


def test_costs_reports_nothing_spent_on_a_fresh_store(store_path, capsys):
    code, out = _run(capsys, "--store", store_path, "costs")
    assert code == 0
    assert "$0.00" in out


def test_sites_reports_nothing_registered_on_a_fresh_store(store_path, capsys):
    code, out = _run(capsys, "--store", store_path, "sites")
    assert code == 0
    assert "no sites" in out


def test_sites_register_requires_a_host(store_path, capsys):
    """The defect: `host` is an optional positional (argparse default ""),
    so `kriko sites register` with nothing after it used to ask the engine
    to register the empty string rather than say what is missing."""
    code = main(["--store", store_path, "sites", "register"])
    err = capsys.readouterr().err
    assert code == 1
    assert "needs a host" in err


def test_operations_reports_nothing_recorded_on_a_fresh_store(store_path, capsys):
    code, out = _run(capsys, "--store", store_path, "operations")
    assert code == 0
    assert "no operations recorded" in out


def test_drafts_reports_nothing_on_a_fresh_store(store_path, capsys):
    code, out = _run(capsys, "--store", store_path, "drafts")
    assert code == 0
    assert "no pack drafts" in out


def test_verify_list_shows_counts_even_when_empty(store_path, capsys):
    code, out = _run(capsys, "--store", store_path, "verify", "--list")
    assert code == 0
    assert "counts:" in out


def test_no_start_without_a_running_engine_fails_cleanly_not_a_traceback(
    store_path, capsys
):
    """Rule: a client that cannot reach an engine gets a one-line message and
    a non-zero exit, never a Python traceback on the reader's screen."""
    code = main(["--store", store_path, "costs", "--no-start"])
    captured = capsys.readouterr()
    assert code == 1
    assert "Traceback" not in captured.err
    assert "no engine is running" in captured.err
