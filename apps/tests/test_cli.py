"""The command line — the reader's whole loop, with no server involved.

The interesting tests here are the two-pack ones. A single installed pack
exercises nothing that a library test does not already cover; two packs from
different authors, with colliding vocabularies, is where this design either
works or does not.
"""

import textwrap

import pytest

from apps.cli import main
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
        textwrap.dedent(spec["terms"]), encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text(
        textwrap.dedent(spec["subjects"]), encoding="utf-8")
    (root / "data" / "claims.yaml").write_text(
        textwrap.dedent(spec["claims"]), encoding="utf-8")
    return build.build(root, tmp_path / f"{name}.kpack")


@pytest.fixture
def store_path(tmp_path):
    return str(tmp_path / "store.sqlite")


@pytest.fixture
def both(tmp_path, store_path):
    for name, spec in (("tools", DRILLISH), ("autos", CARISH)):
        assert main(["--store", store_path, "install",
                     str(_pack(tmp_path, name, spec))]) == 0
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
    _, drill = _run(capsys, "--store", both, "lookup",
                    "brand=makita", "model=DHP484", "--ctx", "usage_hours=800")
    assert "Chuck slips under torque" in drill

    _, car = _run(capsys, "--store", both, "lookup",
                  "make=renault", "model=megane", "--ctx", "usage_km=180000")
    assert "Injector fouling at high mileage" in car


def test_a_query_for_one_pack_does_not_return_the_other(both, capsys):
    _, out = _run(capsys, "--store", both, "lookup",
                  "brand=makita", "model=DHP484", "--ctx", "usage_hours=800")
    assert "Injector fouling" not in out


def test_an_unknown_product_says_so_without_failing(both, capsys):
    code, out = _run(capsys, "--store", both, "lookup",
                     "brand=nobody", "model=nothing")
    assert code == 0
    assert "no_match" in out
    assert "no claims" in out


def test_disable_hides_a_pack_and_enable_brings_it_back(both, capsys):
    _run(capsys, "--store", both, "enable", "tools", "--disable")
    _, hidden = _run(capsys, "--store", both, "lookup",
                     "brand=makita", "model=DHP484", "--ctx", "usage_hours=800")
    assert "Chuck slips" not in hidden

    _run(capsys, "--store", both, "enable", "tools")
    _, back = _run(capsys, "--store", both, "lookup",
                   "brand=makita", "model=DHP484", "--ctx", "usage_hours=800")
    assert "Chuck slips" in back


def test_uninstall_leaves_the_other_pack_answering(both, capsys):
    _run(capsys, "--store", both, "uninstall", "tools")
    _, out = _run(capsys, "--store", both, "lookup",
                  "make=renault", "model=megane", "--ctx", "usage_km=180000")
    assert "Injector fouling" in out


def test_uninstalling_something_absent_is_an_error_not_a_crash(both, capsys):
    assert main(["--store", both, "uninstall", "nope"]) == 1


def test_verbose_explains_the_ranking_and_shows_sources(both, capsys):
    _, out = _run(capsys, "--store", both, "lookup",
                  "brand=makita", "model=DHP484", "--ctx", "usage_hours=800", "-v")
    assert "high severity" in out
    assert "from pack: tools" in out


def test_an_unstated_context_value_is_reported_as_the_reason(both, capsys):
    """Fail-open, visible at the command line: shown, and told why it ranked low."""
    _, out = _run(capsys, "--store", both, "lookup",
                  "brand=makita", "model=DHP484", "-v")
    assert "Chuck slips under torque" in out
    assert "usage_hours not stated" in out


def test_a_bad_argument_is_rejected_clearly(store_path):
    with pytest.raises(SystemExit, match="key=value"):
        main(["--store", store_path, "lookup", "brandmakita"])
