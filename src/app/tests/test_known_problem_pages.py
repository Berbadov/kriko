"""kriko.cc publishes what each catalog knows, as pages a search can find.

`site/tools/render_problems.py` turns every real catalog into one page for each
subject it holds enough claims about. These tests pin what a reader of such a page
is owed (a source to follow, none of the source's own words, nothing made up) and
that the committed pages are what the catalogs say today.
"""

import importlib.util
import json
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


def _claim(model, title, severity, tr_title, url, body="b", advice="a", seen=""):
    retrieved = f", retrieved_at: '{seen}'" if seen else ""
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
        - {{url: "{url}", quote: Words that belong to the forum author.{retrieved}}}
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
    assert "<title>Anvil sorunları ve bilinen arızalar | Kriko</title>" in turkish
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


FIRE = (
    _claim("anvil", "Battery can catch fire while charging", "high", "Pil şarjda alev alabilir", "https://news.invalid/fire")
    + _claim("anvil", "Handle cracks", "medium", "Sap çatlar", "https://forum.invalid/h")
    + _claim("anvil", "Paint chips", "low", "Boya atar", "https://forum.invalid/p")
    # The word is in the body only, in passing: a worn part is not a fire hazard.
    + _claim("anvil", "Piston ring wear", "high", "Segman aşınması", "https://forum.invalid/r", body="Oil can reach a fire wall seal.")
    + _claim("anvil", "Screen burn-in", "medium", "Ekran yanması", "https://forum.invalid/b")
    # A product that is named Fire, and a fault that only sounds like one, are not fires.
    + _claim("anvil", "Fire HD 10 screen cracks", "high", "Ekran çatlar", "https://forum.invalid/hd")
    + _claim("anvil", "Hotend thermal runaway error on startup", "high", "Hata", "https://forum.invalid/t")
    # A fire risk that is not rated high is marked on its card but is not what the hub leads with.
    + _claim("anvil", "Smells like fire when idle", "medium", "Yangın kokusu", "https://forum.invalid/s")
)


def test_a_claim_about_fire_is_marked_as_a_safety_risk_and_the_hub_leads_with_it(tmp_path):
    packs, site = tmp_path / "packs", _site(tmp_path)
    _write_catalog(packs, "tools", FIRE)
    _load().render(packs, site)
    page = (site / "problems" / "anvil" / "index.html").read_text(encoding="utf-8")
    cards = {title: card for title, card in re.findall(r"<h3>.*?</svg>(.*?)</h3>(.*?)</article>", page, re.S)}
    assert "Safety risk" in cards["Battery can catch fire while charging"]
    # Only the claim whose own title says so is marked: not a passing mention, not display burn-in.
    assert sorted(t for t, card in cards.items() if "Safety risk" in card) == [
        "Battery can catch fire while charging", "Smells like fire when idle"]
    assert "2 of these reports describe a fire, explosion or shock risk" in page

    hub = (site / "problems" / "index.html").read_text(encoding="utf-8")
    featured = hub.split('class="serious"')[1].split("</section>")[0]
    assert "Battery can catch fire while charging" in featured
    assert "Piston ring wear" not in featured and "Smells like fire" not in featured and "Fire HD" not in featured
    # The strip links to the claim's own card, which exists on the product page.
    anchor = re.search(r'href="/problems/anvil/#(c-[0-9a-f]+)"', featured).group(1)
    assert f'id="{anchor}"' in page
    # And in Turkish, the same claim is the one featured, in Turkish words.
    turkish = (site / "tr" / "problems" / "index.html").read_text(encoding="utf-8")
    assert "Pil şarjda alev alabilir" in turkish.split('class="serious"')[1] and "Güvenlik riski" in (
        site / "tr" / "problems" / "anvil" / "index.html").read_text(encoding="utf-8")


def test_a_catalog_picks_its_icon_by_name_and_an_unknown_name_is_the_box(tmp_path):
    packs, site = tmp_path / "packs", _site(tmp_path)
    _write_catalog(packs, "tools", ANVIL)
    manifest = packs / "tools" / "pack.toml"
    manifest.write_text(manifest.read_text(encoding="utf-8").replace('license = "CC-BY-SA-4.0"\n', 'license = "CC-BY-SA-4.0"\nicon = "printer"\n'),
                        encoding="utf-8")
    module = _load()
    module.render(packs, site)
    hub = (site / "problems" / "index.html").read_text(encoding="utf-8")
    assert module.ICONS["printer"] in hub and module.ICONS["box"] not in hub

    manifest.write_text(manifest.read_text(encoding="utf-8").replace('icon = "printer"', 'icon = "no-such-drawing"'), encoding="utf-8")
    module.render(packs, site)
    assert module.ICONS["box"] in (site / "problems" / "index.html").read_text(encoding="utf-8")


def test_the_product_with_more_fire_reports_leads_the_hubs_safety_strip_and_says_how_many(tmp_path):
    packs, site = tmp_path / "packs", _site(tmp_path)
    anvil = (_claim("anvil", "Pack caught fire in a garage", "high", "Garajda yandı", "https://news.invalid/a1")
             + _claim("anvil", "Second fire after the recall repair", "high", "Onarımdan sonra yangın", "https://news.invalid/a2")
             + _claim("anvil", "Paint chips", "low", "Boya atar", "https://forum.invalid/p"))
    widget = (_claim("widget", "Charger can start a fire", "high", "Şarj aleti yangın çıkarır", "https://news.invalid/w1")
              + _claim("widget", "Cable frays", "low", "Kablo yıpranır", "https://forum.invalid/c")
              + _claim("widget", "Lid sticks", "low", "Kapak sıkışır", "https://forum.invalid/l"))
    _write_catalog(packs, "tools", widget + anvil)
    _load().render(packs, site)
    featured = (site / "problems" / "index.html").read_text(encoding="utf-8").split('class="serious"')[1].split("</section>")[0]
    assert featured.index("Anvil") < featured.index("Widget")
    assert "Anvil · 2 reports" in featured and "Widget</small>" in featured


def test_of_two_products_with_as_many_fire_reports_the_one_more_sites_agree_on_comes_first(tmp_path):
    packs, site = tmp_path / "packs", _site(tmp_path)
    anvil = (_claim("anvil", "Pack caught fire in a garage", "high", "Garajda yandı", "https://news.invalid/a1")
             + _claim("anvil", "Cable frays", "low", "Kablo yıpranır", "https://forum.invalid/c")
             + _claim("anvil", "Lid sticks", "low", "Kapak sıkışır", "https://forum.invalid/l"))
    widget = (_claim("widget", "Charger can start a fire", "high", "Şarj aleti yangın çıkarır", "https://news.invalid/w1")
              + _claim("widget", "A second fire was reported", "medium", "İkinci yangın", "https://recalls.invalid/w2")
              + _claim("widget", "Lid sticks", "low", "Kapak sıkışır", "https://forum.invalid/l"))
    _write_catalog(packs, "tools", anvil + widget)
    _load().render(packs, site)
    featured = (site / "problems" / "index.html").read_text(encoding="utf-8").split('class="serious"')[1].split("</section>")[0]
    assert featured.index("Widget") < featured.index("Anvil")


def test_the_safety_strip_shows_a_few_and_folds_the_rest_so_the_categories_stay_in_view(tmp_path):
    module = _load()
    packs, site = tmp_path / "packs", _site(tmp_path)
    models = [f"m{n}" for n in range(module.SAFETY_SHOWN + 2)]
    claims = "".join(_claim(m, f"Unit {m} caught fire", "high", "Yandı", f"https://news.invalid/{m}")
                     + _claim(m, f"Handle {m} cracks", "low", "Sap", f"https://forum.invalid/{m}a")
                     + _claim(m, f"Lid {m} sticks", "low", "Kapak", f"https://forum.invalid/{m}b") for m in models)
    extra = "\n" + "\n".join(f"- {{kind: product, label: {m.title()}, identity: {{brand: acme, model: {m}}}}}" for m in models)
    _write_catalog(packs, "tools", claims, extra_subjects=extra)
    module.render(packs, site)
    for path, folded in (("problems", "Show 2 more"), ("tr/problems", "2 tane daha göster")):
        strip = (site / path / "index.html").read_text(encoding="utf-8").split('class="serious"')[1].split("</section>")[0]
        shown, rest = strip.split('<details class="rest">')
        assert shown.count("<li>") == module.SAFETY_SHOWN and rest.count("<li>") == 2 and folded in rest


def _sponsor(**changes):
    row = {"id": "acme-tools", "url": "https://acme.invalid/tools?ref=kriko",
           "name": {"en": "Acme Tools", "tr": "Acme Aletleri"}, "text": {"en": "Anvils that last.", "tr": "Uzun ömürlü örsler."}}
    return {**row, **changes}


def _with_sponsors(tmp_path, rows, claims=ANVIL):
    tmp_path.mkdir(parents=True, exist_ok=True)
    packs, site = tmp_path / "packs", _site(tmp_path)
    _write_catalog(packs, "tools", claims)
    if rows is not None:
        (site / "sponsors.json").write_text(json.dumps(rows), encoding="utf-8")
    _load().render(packs, site)
    return site


def test_a_paid_placement_is_boxed_apart_labelled_and_only_on_the_information_pages(tmp_path):
    site = _with_sponsors(tmp_path, [_sponsor()])
    product = (site / "problems" / "anvil" / "index.html").read_text(encoding="utf-8")
    box = re.search(r'<aside class="sponsored".*?</aside>', product, re.S).group(0)
    assert 'rel="sponsored nofollow noopener"' in box and "Sponsored" in box and "https://acme.invalid/tools?ref=kriko" in box
    assert "changes nothing reported on this page" in box
    # It is never inside a finding, so a reader cannot take it for one.
    assert not any(box in article for article in re.findall(r"<article.*?</article>", product, re.S))
    assert 'class="sponsored"' in (site / "problems" / "tools" / "index.html").read_text(encoding="utf-8")
    # Not on the hub, which is the front door, and in Turkish it is in Turkish.
    assert 'class="sponsored"' not in (site / "problems" / "index.html").read_text(encoding="utf-8")
    turkish = (site / "tr" / "problems" / "anvil" / "index.html").read_text(encoding="utf-8")
    assert "Sponsorlu" in turkish and "Acme Aletleri" in turkish


def test_a_catalog_with_no_placement_shows_none_and_one_aimed_elsewhere_is_not_shown_here(tmp_path):
    for n, rows in enumerate((None, [], [_sponsor(catalogs=["washers"])])):
        site = _with_sponsors(tmp_path / f"case{n}", rows)
        assert 'class="sponsored"' not in (site / "problems" / "anvil" / "index.html").read_text(encoding="utf-8")
    site = _with_sponsors(tmp_path / "aimed", [_sponsor(catalogs=["tools"])])
    assert 'class="sponsored"' in (site / "problems" / "anvil" / "index.html").read_text(encoding="utf-8")


def test_a_placement_that_is_not_https_or_is_not_in_the_pages_language_is_not_shown(tmp_path, capsys):
    rows = [_sponsor(id="a", url="http://acme.invalid/"), _sponsor(id="b", url="javascript:alert(1)"),
            _sponsor(id="c", name={"en": "English only"}, text={"en": "Only in English."})]
    site = _with_sponsors(tmp_path, rows)
    english = (site / "problems" / "anvil" / "index.html").read_text(encoding="utf-8")
    assert "English only" in english and "javascript" not in english and "http://acme" not in english
    assert 'class="sponsored"' not in (site / "tr" / "problems" / "anvil" / "index.html").read_text(encoding="utf-8")
    assert "a is not a placement" in capsys.readouterr().err


def test_the_page_of_every_safety_report_lists_each_product_and_the_hub_links_to_it(tmp_path):
    site = _with_sponsors(tmp_path, None, claims=FIRE)
    page = (site / "problems" / "safety" / "index.html").read_text(encoding="utf-8")
    assert "Battery can catch fire while charging" in page and 'href="/problems/anvil/#c-' in page
    assert "Piston ring wear" not in page and "Smells like fire" not in page
    hub = (site / "problems" / "index.html").read_text(encoding="utf-8")
    assert 'href="/problems/safety/">All 1 products with safety reports' in hub
    assert "Yangın, patlama" in (site / "tr" / "problems" / "safety" / "index.html").read_text(encoding="utf-8")
    sitemap = (site / "sitemap-problems.xml").read_text(encoding="utf-8")
    assert "<loc>https://kriko.cc/problems/safety/</loc>" in sitemap


def test_a_catalog_with_no_safety_report_has_no_safety_page_and_a_product_cannot_take_its_address(tmp_path):
    site = _with_sponsors(tmp_path, None, claims=ANVIL.replace("Widget", "x") + _claim("widget", "Pack caught fire", "low", "Yandı", "https://n.invalid/1"))
    assert not (site / "problems" / "safety").exists()
    assert "safety reports" not in (site / "problems" / "index.html").read_text(encoding="utf-8")
    (tmp_path / "again").mkdir()
    packs = tmp_path / "again" / "packs"
    _write_catalog(packs, "tools", ANVIL, extra_subjects="\n- {kind: product, label: Safety, identity: {brand: acme, model: safety}}")
    extra = "".join(_claim("safety", f"Fault {n}", "high", f"Arıza {n}", f"https://forum.invalid/s{n}") for n in range(3))
    (packs / "tools" / "data" / "claims.yaml").write_text(textwrap.dedent(ANVIL + extra), encoding="utf-8")
    out = _site(tmp_path / "again")
    _load().render(packs, out)
    assert not (out / "problems" / "safety").exists() and (out / "problems" / "safety-3" / "index.html").is_file()


def test_a_page_says_when_it_was_last_checked_and_where_it_sits_to_a_search_engine(tmp_path):
    claims = (_claim("anvil", "Pack caught fire in a garage", "high", "Garajda yandı", "https://news.invalid/a", seen="2026-10-02T09:00:00+00:00")
              + _claim("anvil", "Handle cracks", "medium", "Sap çatlar", "https://forum.invalid/h", seen="2026-09-20T09:00:00+00:00")
              + _claim("anvil", "Paint chips", "low", "Boya atar", "https://forum.invalid/p"))
    site = _with_sponsors(tmp_path, None, claims=claims)
    page = (site / "problems" / "anvil" / "index.html").read_text(encoding="utf-8")
    blocks = [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)]
    kinds = {b["@type"]: b for b in blocks}
    assert kinds["Article"]["dateModified"] == "2026-10-02"
    assert [i["name"] for i in kinds["BreadcrumbList"]["itemListElement"]] == ["Known problems", "Tools", "Anvil"]
    assert "<title>Anvil: known problems and safety risks | Kriko</title>" in page
    sitemap = (site / "sitemap-problems.xml").read_text(encoding="utf-8")
    assert re.search(r"<loc>https://kriko.cc/problems/anvil/</loc>\s*<lastmod>2026-10-02</lastmod>", sitemap)
    # A page with no source date says nothing rather than a guess.
    assert not re.search(r"<loc>https://kriko.cc/problems/safety/</loc>\s*<lastmod>", sitemap) or "2026-10-02" in sitemap


def test_structured_data_cannot_close_the_script_tag_it_sits_in():
    assert "</script>" not in _load()._structured({"name": "x</script><script>alert(1)</script>"}).replace("</script>\n", "", 1)
