"""kriko.cc publishes what each catalog knows, as pages a search can find.

`site/tools/render_problems.py` turns every real catalog into one page for each
subject it holds enough claims about. These tests pin what a reader of such a page
is owed (a source to follow, none of the source's own words, nothing made up) and
that the committed pages are what the catalogs say today.
"""

import importlib.util
import re
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "site" / "tools" / "render_problems.py"


def _load():
    spec = importlib.util.spec_from_file_location("render_problems", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TERMS = """
    - {term_id: product, role: subject_kind}
    - {term_id: brand, role: attribute, datatype: text, match: {required: true}}
    - {term_id: model, role: attribute, datatype: text, match: {required: true}}
    - {term_id: mech, role: domain}
"""


def _claim(model, title, severity, tr_title, url, body="b", advice="a"):
    return f"""
    - subject: {{kind: product, identity: {{brand: acme, model: {model}}}}}
      kind: known_issue
      domain: mech
      severity: {severity}
      detection: diagnostic
      text:
        en: {{title: "{title}", body: {body}, advice: {advice}}}
        tr: {{title: "{tr_title}", body: gövde, advice: öneri}}
      evidence:
        - {{url: "{url}", quote: Words that belong to the forum author.}}
"""


def _write_catalog(packs: Path, name: str, claims: str, *, synthetic=False, extra_subjects=""):
    root = packs / name
    for sub in ("vocabulary", "data", "research"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    flags = "synthetic = true\n" if synthetic else ""
    (root / "pack.toml").write_text(
        f'[pack]\nid = "{name}"\nname = "{name.title()}"\nversion = "1.2.3"\nlicense = "CC-BY-SA-4.0"\n'
        f'languages = ["en", "tr"]\n{flags}[identity]\nproduct = ["brand", "model"]\n',
        encoding="utf-8",
    )
    (root / "vocabulary" / "terms.yaml").write_text(textwrap.dedent(TERMS), encoding="utf-8")
    subjects = "\n".join(
        f"- {{kind: product, label: {model.title()}, identity: {{brand: acme, model: {model}}}}}"
        for model in ("anvil", "widget")
    ) + extra_subjects
    (root / "data" / "subjects.yaml").write_text(subjects + "\n", encoding="utf-8")
    (root / "data" / "claims.yaml").write_text(textwrap.dedent(claims), encoding="utf-8")
    (root / "research" / "principle.md").write_text("Only the expensive.", encoding="utf-8")
    (root / "research" / "templates.yaml").write_text('- "{alias} faults"\n', encoding="utf-8")


def _site(tmp_path: Path) -> Path:
    site = tmp_path / "site"
    site.mkdir()
    (site / "styles.css").write_text("body{}", encoding="utf-8")
    return site


ANVIL = (
    _claim("anvil", "Handle cracks (anvil_handle)", "medium", "Sap çatlar", "https://forum.invalid/a")
    + _claim("anvil", "Head loosens", "high", "Kafa gevşer", "https://repair.invalid/b")
    + _claim("anvil", "Paint chips", "low", "Boya atar", "https://forum.invalid/c")
)
THIN = _claim("widget", "One lonely report", "high", "Tek rapor", "https://forum.invalid/d")


def test_a_subject_with_enough_claims_gets_a_page_in_each_language_and_a_hub(tmp_path):
    packs, site = tmp_path / "packs", _site(tmp_path)
    _write_catalog(packs, "tools", ANVIL + THIN)
    written = _load().render(packs, site)
    # A hub, a page for the catalog, and a page for each product with enough claims, in each language.
    assert written == ["/problems/", "/problems/anvil/", "/problems/tools/",
                       "/tr/problems/", "/tr/problems/anvil/", "/tr/problems/tools/"]

    english = (site / "problems" / "anvil" / "index.html").read_text(encoding="utf-8")
    turkish = (site / "tr" / "problems" / "anvil" / "index.html").read_text(encoding="utf-8")
    assert "<title>Anvil: known problems | Kriko</title>" in english
    assert "<title>Anvil: bilinen sorunlar | Kriko</title>" in turkish
    assert 'hreflang="tr" href="https://kriko.cc/tr/problems/anvil/"' in english
    assert 'hreflang="en" href="https://kriko.cc/problems/anvil/"' in turkish
    assert "Kafa gevşer" in turkish and "Head loosens" not in turkish

    # The reader can follow each claim to the page it came from...
    assert 'href="https://repair.invalid/b"' in english
    # ...and is not handed that page's own words.
    assert "belong to the forum author" not in english

    # Worst first, so the first thing read is the thing that costs most.
    assert english.index("Head loosens") < english.index("Handle cracks") < english.index("Paint chips")
    # The catalog's own identifier means nothing to a reader.
    assert "anvil_handle" not in english and "Handle cracks" in english

    assert "CC-BY-SA-4.0" in english and "1.2.3" in english


def test_a_subject_with_too_few_claims_gets_no_page(tmp_path):
    packs, site = tmp_path / "packs", _site(tmp_path)
    _write_catalog(packs, "tools", ANVIL + THIN)
    _load().render(packs, site)
    assert not (site / "problems" / "widget").exists()
    assert "Widget" not in (site / "problems" / "index.html").read_text(encoding="utf-8")


def test_a_synthetic_catalog_is_never_published(tmp_path):
    # The worked example's claims are made up; on a real address they would be false statements.
    packs, site = tmp_path / "packs", _site(tmp_path)
    _write_catalog(packs, "example", ANVIL, synthetic=True)
    assert _load().render(packs, site) == []
    assert not (site / "problems").exists() and not (site / "sitemap-problems.xml").exists()


def test_the_sitemap_lists_exactly_the_pages_written_with_their_alternates(tmp_path):
    packs, site = tmp_path / "packs", _site(tmp_path)
    _write_catalog(packs, "tools", ANVIL)
    written = _load().render(packs, site)
    sitemap = (site / "sitemap-problems.xml").read_text(encoding="utf-8")
    assert sorted(re.findall(r"<loc>https://kriko\.cc([^<]+)</loc>", sitemap)) == sorted(written)
    assert 'hreflang="tr" href="https://kriko.cc/tr/problems/anvil/"' in sitemap


def test_a_second_run_changes_no_file(tmp_path):
    # Nothing in a page is a date or a random value, so a diff means the knowledge changed.
    packs, site = tmp_path / "packs", _site(tmp_path)
    _write_catalog(packs, "tools", ANVIL)
    render = _load().render
    render(packs, site)
    first = {p: p.read_bytes() for p in site.rglob("*") if p.is_file()}
    render(packs, site)
    assert {p: p.read_bytes() for p in site.rglob("*") if p.is_file()} == first


def test_the_pages_in_the_repo_are_what_the_catalogs_say_today(tmp_path):
    # A stale page would go on telling readers a claim the catalog has since dropped.
    site = _site(tmp_path)
    (site / "styles.css").write_bytes((REPO / "site" / "styles.css").read_bytes())
    _load().render(REPO / "packs", site)
    for tree in ("problems", "tr/problems"):
        fresh = {p.relative_to(site): p.read_bytes() for p in (site / tree).rglob("*") if p.is_file()}
        shipped = {p.relative_to(REPO / "site"): p.read_bytes() for p in (REPO / "site" / tree).rglob("*") if p.is_file()}
        assert fresh.keys() == shipped.keys(), f"run site/tools/render_problems.py: pages differ in {tree}"
        stale = [str(name) for name in fresh if fresh[name] != shipped[name]]
        assert not stale, f"run site/tools/render_problems.py, these pages are out of date: {stale[:3]}"
    assert (site / "sitemap-problems.xml").read_bytes() == (REPO / "site" / "sitemap-problems.xml").read_bytes()


def test_the_hub_files_a_part_under_each_whole_thing_it_is_fitted_to_grouped_by_make(tmp_path):
    # Readers search for the thing they are about to buy, not for its gearbox: the hub is
    # organised by catalog, then by make, and a part's page is reached through the cars it fits.
    packs, site = tmp_path / "packs", _site(tmp_path)
    root = packs / "rigs"
    for sub in ("vocabulary", "data", "research"):
        (root / sub).mkdir(parents=True)
    (root / "pack.toml").write_text(
        '[pack]\nid = "rigs"\nname = "Rigs"\nversion = "1.0.0"\nlicense = "CC0-1.0"\nlanguages = ["en", "tr"]\n'
        '[identity]\nproduct = ["make", "model"]\nengine = ["code"]\n', encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(textwrap.dedent("""
        - {term_id: product, role: subject_kind}
        - {term_id: engine, role: subject_kind}
        - {term_id: part_of, role: predicate}
        - {term_id: make, role: attribute, datatype: text, match: {required: true}}
        - {term_id: model, role: attribute, datatype: text, match: {required: true}}
        - {term_id: code, role: attribute, datatype: text, match: {required: true}}
        - {term_id: mech, role: domain}
    """), encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text(textwrap.dedent("""
        - kind: engine
          label: Zeta Engine
          identity: {code: zeta}
        - kind: product
          label: Acme Roadster 2.0
          identity: {make: acme, model: roadster}
          relations:
            - {predicate: part_of, object: {kind: engine, identity: {code: zeta}}}
        - kind: product
          label: Borealis Cruiser 1.6
          identity: {make: borealis, model: cruiser}
          relations:
            - {predicate: part_of, object: {kind: engine, identity: {code: zeta}}}
    """), encoding="utf-8")
    claims = "".join(
        f"""
    - subject: {{kind: engine, identity: {{code: zeta}}}}
      kind: known_issue
      domain: mech
      severity: high
      text:
        en: {{title: "Problem {n}", body: b, advice: a}}
        tr: {{title: "Sorun {n}", body: b, advice: a}}
      evidence:
        - {{url: "https://forum.invalid/{n}", quote: Reported {n}.}}
""" for n in (1, 2, 3))
    (root / "data" / "claims.yaml").write_text(textwrap.dedent(claims), encoding="utf-8")
    (root / "research" / "principle.md").write_text("Only the expensive.", encoding="utf-8")
    (root / "research" / "templates.yaml").write_text('- "{alias} faults"\n', encoding="utf-8")

    _load().render(packs, site)
    category = (site / "problems" / "rigs" / "index.html").read_text(encoding="utf-8")
    assert "<summary>Acme<span>" in category and "<summary>Borealis<span>" in category
    # Each make lists its own car, and that car links to the engine page it shares.
    acme = category.split("<summary>Acme<span>")[1].split("</details>")[0]
    assert "Acme Roadster 2.0" in acme and 'href="/problems/zeta-engine/"' in acme and "Borealis" not in acme
    # The hub is the front door: a card for the catalog, and no list of every product.
    hub = (site / "problems" / "index.html").read_text(encoding="utf-8")
    assert 'href="/problems/rigs/"' in hub and "Acme Roadster 2.0" not in hub
    # The engine's own page says which cars it is found on.
    page = (site / "problems" / "zeta-engine" / "index.html").read_text(encoding="utf-8")
    assert "Acme Roadster 2.0" in page and "Borealis Cruiser 1.6" in page


def _proposal(model, title):
    """A claim an agent proposed that no run has found a page for yet."""
    return f"""
    - subject: {{kind: product, identity: {{brand: acme, model: {model}}}}}
      kind: known_issue
      domain: mech
      severity: high
      text:
        en: {{title: "{title}", body: b, advice: a}}
        tr: {{title: "{title} (tr)", body: b, advice: a}}
"""


def test_a_claim_with_no_source_page_is_never_published(tmp_path):
    # An agent's draft arrives as proposals; only a run that finds the page makes one a finding.
    packs, site = tmp_path / "packs", _site(tmp_path)
    unproven_only = "".join(_proposal("widget", f"Rumour {n}") for n in range(4))
    _write_catalog(packs, "tools", ANVIL + _proposal("anvil", "Unproven rumour") + unproven_only)
    _load().render(packs, site)
    english = (site / "problems" / "anvil" / "index.html").read_text(encoding="utf-8")
    assert "Head loosens" in english and "Unproven rumour" not in english
    # Four proposals and no source is still a subject with nothing to publish.
    assert not (site / "problems" / "widget").exists()


def test_a_long_page_opens_with_its_problems_listed_and_a_short_one_does_not(tmp_path):
    packs, site = tmp_path / "packs", _site(tmp_path)
    _write_catalog(packs, "tools", ANVIL + _claim("anvil", "Grip wears", "medium", "Tutamak aşınır", "https://forum.invalid/e"))
    _load().render(packs, site)
    page = (site / "problems" / "anvil" / "index.html").read_text(encoding="utf-8")
    # Four claims: a list of their titles, each linked to its own card, worst first.
    glance = page.split('<nav class="glance"')[1].split("</nav>")[0]
    assert glance.count("<li") == 4 and glance.index("Head loosens") < glance.index("Paint chips")
    anchors = re.findall(r'href="#(c-[0-9a-f]+)"', glance)
    assert len(anchors) == 4 and all(f'id="{anchor}"' in page for anchor in anchors)
    # The page says where it sits, so a reader who landed on it can climb back out.
    assert '<a href="/problems/">Known problems</a> › <a href="/problems/tools/">Tools</a>' in page

    _write_catalog(packs, "tools", ANVIL)
    _load().render(packs, site)
    assert 'class="glance"' not in (site / "problems" / "anvil" / "index.html").read_text(encoding="utf-8")
