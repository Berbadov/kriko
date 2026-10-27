"""Write a public page for every part or product a catalog holds claims about.

    PYTHONPATH=src python site/tools/render_problems.py

Search is the one free way to reach a person who is about to buy something with a
known weak part, so each catalog is also published as pages on kriko.cc: one
for each subject it holds enough claims about, in each language the claims are
written in, plus a hub that lists them. Nothing here names a category. The pages
are read from the catalog the way the app reads it (`kriko.pack.build` turns
`packs/<name>` into a catalog file, and this reads that), so a new catalog or a
new product in an old one gets its pages with no edit here.

What a page carries: the claim's title, body and advice, how it is found, and a
link to each page it was reported on. It never carries the quote the claim was
checked against; that text belongs to its author, the link sends the reader there.

What is never published:
  * a catalog that declares itself `synthetic` (the worked example), because a
    made-up claim on a real address is a false statement;
  * a subject with fewer than MIN_CLAIMS claims, because a page of one line is
    thin and a reader who lands on it is let down.

Output is a pure function of the catalogs and `styles.css`: no dates, nothing
random, so a second run changes no file and a diff means the knowledge changed.
`site/problems/`, `site/tr/problems/` and `site/sitemap-problems.xml` are owned by
this script and rewritten whole.
"""

import argparse
import hashlib
import html
import re
import shutil
import sqlite3
import sys
import tempfile
import tomllib
from pathlib import Path

import yaml

ORIGIN = "https://kriko.cc"
MIN_CLAIMS = 3
LANGS = ("en", "tr")
SEVERITY_ORDER = ("high", "medium", "low")
MORE_LINKS = 8  # other products of the same catalog linked from a product page
GLANCE_FROM = 4  # a page with this many claims opens with a list of their titles
OPEN_UP_TO = 12  # a group of more products than this starts folded

# The site's own words, per language. The claims' words come from the catalog.
UI = {
    "en": {
        "html_lang": "en",
        "prefix": "",
        "home": "/",
        "get": "/#get",
        "switch": "Türkçe",
        "crumb": "Known problems",
        "glance": "At a glance",
        "more": "More in {category}",
        "all_in": "All {category}",
        "cat_title": "{name}: known problems",
        "cat_lead": "{n} products with sourced known problems. Pick one to see what to check before you buy.",
        "cat_desc": "Sourced known problems for {n} products in {name}, with what to check before you buy.",
        "products": "{n} products",
        "title": "{label}: known problems",
        "lead": "{n} sourced reports, with what to check before you buy. Each one links to the page it was reported on.",
        "desc": "{n} sourced problems reported for {label}, with what to check before you buy. {top}",
        "check": "What to check",
        "sources": "Reported on",
        "fits": "Found on these models",
        "group": {"high": "Costly or dangerous", "medium": "Worth checking", "low": "Minor"},
        "detect": {
            "diagnostic": "Found with a diagnostic scan",
            "visual": "Found by looking",
            "test_drive": "Noticed on a test drive",
            "history_check": "Shown by the service history",
        },
        "cta_h": "Check the one you are about to buy",
        "cta_p": "Kriko reads a listing and tells you which of these apply to that exact product. It runs on your computer, needs no account and is free.",
        "cta_b": "Get Kriko",
        "note": "These reports come from the pages linked under each item: owner forums, repair guides and workshops. They are not a diagnosis of any one unit, and a careful check of the one you are buying still applies.",
        "licence": "Text from the Kriko {name} catalog, version {version}, under the {license} license.",
        "hub_title": "Known problems, by product and part",
        "hub_lead": "Pick a category. Each product page lists what owners and repairers report going wrong with it, every report linked to the page it came from.",
        "hub_desc": "Sourced known problems for specific products and parts, with what to check before you buy.",
        "hub_other": "Other",
        "reports": "{n} reports",
        "footer_home": "kriko.cc",
        "footer_help": "Help and feedback",
        "privacy": "Privacy",
    },
    "tr": {
        "html_lang": "tr",
        "prefix": "/tr",
        "home": "/tr/",
        "get": "/tr/#get",
        "switch": "English",
        "crumb": "Bilinen sorunlar",
        "glance": "Bir bakışta",
        "more": "{category} içinde diğerleri",
        "all_in": "Tüm {category}",
        "cat_title": "{name}: bilinen sorunlar",
        "cat_lead": "Kaynaklı bilinen sorunları olan {n} ürün. Satın almadan önce neye bakacağınızı görmek için birini seçin.",
        "cat_desc": "{name} kategorisinde {n} ürün için kaynaklı bilinen sorunlar ve satın almadan önce neye bakılacağı.",
        "products": "{n} ürün",
        "title": "{label}: bilinen sorunlar",
        "lead": "{n} kaynaklı rapor ve satın almadan önce neye bakmanız gerektiği. Her biri, bildirildiği sayfaya bağlantı verir.",
        "desc": "{label} için bildirilen {n} kaynaklı sorun ve satın almadan önce neye bakılacağı. {top}",
        "check": "Neye bakmalı",
        "sources": "Bildirildiği yer",
        "fits": "Şu modellerde görülür",
        "group": {"high": "Pahalı ya da tehlikeli", "medium": "Bakmaya değer", "low": "Küçük"},
        "detect": {
            "diagnostic": "Arıza tarama ile bulunur",
            "visual": "Gözle bakınca bulunur",
            "test_drive": "Test sürüşünde fark edilir",
            "history_check": "Servis geçmişinden anlaşılır",
        },
        "cta_h": "Satın alacağınız ürünü bu listeyle karşılaştırın",
        "cta_p": "Kriko bir ilanı okur ve bu sorunlardan hangilerinin o ürüne uyduğunu söyler. Bilgisayarınızda çalışır, hesap gerektirmez ve ücretsizdir.",
        "cta_b": "Kriko'yu indir",
        "note": "Bu maddeler, her birinin altında bağlantısı verilen sayfalardan derlenmiştir: kullanıcı forumları, onarım rehberleri ve servisler. Belirli bir ürünün teşhisi değildir; satın alacağınız ürünü dikkatle kontrol etmeniz yine de gerekir.",
        "licence": "Metin, Kriko {name} kataloğundan (sürüm {version}) alınmıştır, {license} lisansıyla.",
        "hub_title": "Bilinen sorunlar: ürün ve parça bazında",
        "hub_lead": "Bir kategori seçin. Her ürün sayfası, sahiplerin ve tamircilerin neyin bozulduğunu bildirdiğini listeler; her rapor, geldiği sayfaya bağlantı verir.",
        "hub_desc": "Belirli ürün ve parçalar için kaynaklı bilinen sorunlar ve satın almadan önce neye bakılacağı.",
        "hub_other": "Diğer",
        "reports": "{n} rapor",
        "footer_home": "kriko.cc",
        "footer_help": "Yardım ve geri bildirim",
        "privacy": "Gizlilik",
    },
}

# A claim's words sometimes carry the catalog's own identifier ("... (clio5_body)").
# It means nothing to a reader, so it is taken out wherever it appears.
IDENTIFIER = re.compile(r"\s*\(?\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b\)?")


def clean(text: str) -> str:
    return re.sub(r"\s{2,}", " ", IDENTIFIER.sub("", text or "")).strip()


def slugify(label: str) -> str:
    folded = label.lower().translate(str.maketrans("ıçğöşüİ", "icgosui"))
    return re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", folded)).strip("-") or "page"


def stylesheet_hash(site: Path) -> str:
    return hashlib.sha256((site / "styles.css").read_bytes()).hexdigest()[:12]


def real_catalogs(packs_dir: Path):
    """Each `packs/<name>` that is a real catalog, as (path, manifest). Synthetic ones are left out."""
    for root in sorted(p for p in packs_dir.iterdir() if (p / "pack.toml").is_file()):
        manifest = tomllib.loads((root / "pack.toml").read_text(encoding="utf-8")).get("pack", {})
        if manifest.get("synthetic"):
            continue
        yield root, manifest


def build_catalog(root: Path, out: Path) -> Path:
    """Build `root` the way `kriko build` does: a pack that ships its own builder is built by it.

    The generic builder pointed at such a pack succeeds and returns a catalog with
    nothing in it, which here would be a site with no pages and no error.
    """
    from kriko.pack import build

    if not (root / "build.py").exists():
        return build.build(root, out)
    import importlib

    holder = str(root.resolve().parent.parent)  # the directory that holds `packs/`
    if holder not in sys.path:
        sys.path.insert(0, holder)
    result = importlib.import_module(f"packs.{root.name}.build").build(out)
    return Path(result[0] if isinstance(result, tuple) else result)


def read_catalog(path: Path) -> dict:
    """Everything a page needs from one built catalog file, as plain data."""
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        name, version, license_, manifest = conn.execute(
            "SELECT name, version, license, manifest_json FROM packs").fetchone()
        declared = yaml.safe_load(manifest) or {}
        subjects = {sid: {"label": label, "kind": kind, "claims": [], "products": [], "group": ""}
                    for sid, label, kind in conn.execute("SELECT subject_id, label, kind FROM subjects")}
        sources: dict[str, list[tuple[str, str]]] = {}
        for claim_id, url, domain in conn.execute(
            "SELECT e.claim_id, s.url, s.domain FROM evidence e JOIN sources s USING (source_id) ORDER BY s.url"
        ):
            sources.setdefault(claim_id, []).append((url, domain))
        claims = {}
        for claim_id, subject_id, severity, detection in conn.execute(
            "SELECT claim_id, subject_id, severity, detection FROM claims"
        ):
            claims[claim_id] = {"id": claim_id, "severity": severity, "detection": detection,
                                "sources": list(dict.fromkeys(sources.get(claim_id, []))), "text": {}}
            subjects[subject_id]["claims"].append(claims[claim_id])
        for claim_id, lang, title, body, advice in conn.execute(
            "SELECT claim_id, lang, title, body, advice FROM claim_text"
        ):
            claims[claim_id]["text"][lang] = {"title": clean(title), "body": clean(body), "advice": clean(advice)}
        parts = set()
        for sid, oid in conn.execute("SELECT subject_id, object_id FROM relations WHERE predicate = 'part_of'"):
            if oid in subjects and sid in subjects:
                subjects[oid]["products"].append(subjects[sid]["label"])
                parts.add(oid)
        # A whole thing is browsed by its first identity key (the make, the brand): the one
        # the pack lists first. A part has no such key worth grouping by, so it gets none.
        first_key = {kind: keys[0] for kind, keys in declared.get("identity", {}).items() if keys}
        for sid, key, value in conn.execute(
            "SELECT subject_id, key, value_text FROM attributes WHERE is_identity = 1 AND value_text IS NOT NULL"
        ):
            subject = subjects.get(sid)
            if subject and sid not in parts and key == first_key.get(subject["kind"]) and value:
                label = subject["label"]
                subject["group"] = label[:len(value)] if label.lower().startswith(value.lower()) else value.title()
        by_label = {s["label"]: s for s in subjects.values()}
        groups = {label: by_label[label]["group"]
                  for label in {l for s in subjects.values() for l in s["products"]} if label in by_label}
        return {"name": name, "names": declared.get("names") or {}, "version": version, "license": license_,
                "subjects": subjects, "groups": groups}
    finally:
        conn.close()


def _e(text) -> str:
    return html.escape(str(text), quote=True)


def _chrome(lang: str, *, title: str, description: str, path: str, alternates: dict[str, str], depth: int,
            css: str, body: str) -> str:
    ui = UI[lang]
    up = "../" * depth
    links = "".join(f'  <link rel="alternate" hreflang="{code}" href="{ORIGIN}{url}">\n' for code, url in alternates.items())
    if alternates:
        links += f'  <link rel="alternate" hreflang="x-default" href="{ORIGIN}{alternates.get("en") or next(iter(alternates.values()))}">\n'
    other = "tr" if lang == "en" else "en"
    switch = f'<a class="back-link" href="{alternates[other]}" hreflang="{other}" lang="{other}">{_e(ui["switch"])}</a>' if other in alternates else ""
    return f"""<!DOCTYPE html>
<html lang="{ui["html_lang"]}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light dark">
  <title>{_e(title)} | Kriko</title>
  <meta name="description" content="{_e(description)}">
  <link rel="icon" href="{up}assets/icon-32.png">
  <link rel="stylesheet" href="{up}styles.css?v={css}">
  <link rel="canonical" href="{ORIGIN}{path}">
{links}  <meta property="og:type" content="article">
  <meta property="og:site_name" content="Kriko">
  <meta property="og:title" content="{_e(title)}">
  <meta property="og:description" content="{_e(description)}">
  <meta property="og:url" content="{ORIGIN}{path}">
  <meta property="og:image" content="{ORIGIN}/assets/share-card.jpg">
  <meta name="twitter:card" content="summary_large_image">
</head>
<body>
  <header class="topbar">
    <div class="wrap bar">
      <a class="brand" href="{ui["home"]}" aria-label="Kriko"><picture><source srcset="{up}assets/kriko-wordmark-white.svg" media="(prefers-color-scheme: dark)"><img src="{up}assets/kriko-wordmark.svg" alt="Kriko" width="96" height="32"></picture></a>
      {switch}
    </div>
  </header>
  <main id="main" class="policy problems">
    <div class="wrap narrow">
{body}
    </div>
  </main>
  <footer class="footer">
    <div class="wrap footer-grid">
      <p>{_e(ui["footer_home"])}</p>
      <nav aria-label="Footer"><a href="{ui["home"]}">{_e(ui["footer_home"])}</a><a href="/privacy/" hreflang="en">{_e(ui["privacy"])}</a><a href="https://github.com/Berbadov/kriko/issues">{_e(ui["footer_help"])}</a></nav>
    </div>
  </footer>
</body>
</html>
"""


def _claim_html(claim: dict, lang: str) -> str:
    ui = UI[lang]
    text = claim["text"][lang]
    severity = claim["severity"] if claim["severity"] in SEVERITY_ORDER else "low"
    detect = ui["detect"].get(claim["detection"], "")
    sources = ", ".join(f'<a href="{_e(url)}" rel="noopener">{_e(domain or url)}</a>' for url, domain in claim["sources"])
    parts = [f'      <article class="claim sev-{severity}" id="c-{_e(claim["id"][:8])}">',
             f'        <h3>{_e(text["title"])}</h3>']
    if detect:
        parts.append(f'        <p class="how">{_e(detect)}</p>')
    if text["body"]:
        parts.append(f'        <p>{_e(text["body"])}</p>')
    if text["advice"]:
        parts.append(f'        <p class="check"><strong>{_e(ui["check"])}.</strong> {_e(text["advice"])}</p>')
    if sources:
        parts.append(f'        <p class="src">{_e(ui["sources"])}: {sources}</p>')
    parts.append("      </article>")
    return "\n".join(parts)


def _subject_claims(subject: dict, lang: str) -> list[dict]:
    """The subject's claims that have words in `lang` and a source page, worst first, one for each title.

    A claim nobody has found a page for is a proposal, not a finding: it stays out, whatever it says.
    """
    seen, picked = set(), []
    ranked = sorted((c for c in subject["claims"] if c["sources"] and lang in c["text"] and c["text"][lang]["title"]),
                    key=lambda c: (SEVERITY_ORDER.index(c["severity"]) if c["severity"] in SEVERITY_ORDER else 9,
                                   c["text"][lang]["title"], c["id"]))
    for claim in ranked:
        key = claim["text"][lang]["title"].casefold()
        if key not in seen:
            seen.add(key)
            picked.append(claim)
    return picked


def _chip(entry: dict, lang: str) -> str:
    return (f'<li><a href="{UI[lang]["prefix"]}/problems/{entry["slug"]}/">{_e(entry["label"])}'
            f'<small>{entry["counts"][lang]}</small></a></li>')


def _category_name(entry: dict, lang: str) -> str:
    return entry["names"].get(lang) or entry["catalog"]


def _neighbours(entry: dict, entries: list[dict], lang: str) -> list[dict]:
    """Up to MORE_LINKS other products of the same catalog: its own make or brand first."""
    same = sorted((e for e in entries if e["catalog"] == entry["catalog"] and e is not entry and lang in e["have"]),
                  key=lambda e: (e["group"] != entry["group"] or not entry["group"], e["label"]))
    return same[:MORE_LINKS]


def _subject_page(catalog: dict, entry: dict, subject: dict, lang: str, claims: list[dict], css: str,
                  entries: list[dict]) -> str:
    ui = UI[lang]
    label = subject["label"]
    path = f'{ui["prefix"]}/problems/{entry["slug"]}/'
    alternates = {code: f'{UI[code]["prefix"]}/problems/{entry["slug"]}/' for code in LANGS if code in entry["have"]}
    top = "; ".join(c["text"][lang]["title"] for c in claims[:2])
    category = _category_name(entry, lang)
    sections = []
    for severity in SEVERITY_ORDER:
        group = [c for c in claims if c["severity"] == severity]
        if group:
            sections.append(f'      <h2>{_e(ui["group"][severity])}</h2>\n' + "\n".join(_claim_html(c, lang) for c in group))
    glance = ""
    if len(claims) >= GLANCE_FROM:
        items = "".join(
            f'<li class="sev-{c["severity"] if c["severity"] in SEVERITY_ORDER else "low"}">'
            f'<a href="#c-{_e(c["id"][:8])}">{_e(c["text"][lang]["title"])}</a></li>' for c in claims)
        glance = f'      <nav class="glance" aria-label="{_e(ui["glance"])}"><h2>{_e(ui["glance"])}</h2><ul>{items}</ul></nav>\n'
    fits = ""
    if subject["products"]:
        items = "".join(f"<li>{_e(p)}</li>" for p in sorted(set(subject["products"])))
        fits = f'      <h2>{_e(ui["fits"])}</h2>\n      <ul>{items}</ul>\n'
    near = _neighbours(entry, entries, lang)
    more = ""
    if near:
        chips = "".join(_chip(e, lang) for e in near)
        more = (f'      <h2>{_e(ui["more"].format(category=category))}</h2>\n      <ul class="chips">{chips}</ul>\n'
                f'      <p><a href="{ui["prefix"]}/problems/{entry["catalog_slug"]}/">{_e(ui["all_in"].format(category=category))}</a></p>\n')
    body = (f'      <p class="crumb"><a href="{ui["prefix"]}/problems/">{_e(ui["crumb"])}</a> › '
            f'<a href="{ui["prefix"]}/problems/{entry["catalog_slug"]}/">{_e(category)}</a></p>\n'
            f'      <h1>{_e(ui["title"].format(label=label))}</h1>\n'
            f'      <p class="lead">{_e(ui["lead"].format(n=len(claims)))}</p>\n'
            + glance + "\n".join(sections) + "\n" + fits + more +
            f'      <div class="short"><h2>{_e(ui["cta_h"])}</h2><p>{_e(ui["cta_p"])}</p>'
            f'<p><a class="button" href="{ui["get"]}">{_e(ui["cta_b"])}</a></p></div>\n'
            f'      <p class="fine">{_e(ui["note"])}</p>\n'
            f'      <p class="fine">{_e(ui["licence"].format(name=catalog["name"], version=catalog["version"], license=catalog["license"]))}</p>')
    description = ui["desc"].format(label=label, n=len(claims), top=top)
    description = description if len(description) <= 158 else description[:155].rsplit(" ", 1)[0] + "…"
    return _chrome(lang, title=ui["title"].format(label=label), description=description, path=path,
                   alternates=alternates, depth=3 if lang == "tr" else 2, css=css, body=body)


def _category_page(lang: str, items: list[dict], css: str, have: set[str]) -> str:
    """One catalog's page: its products under their make or brand, a part under each product it fits."""
    ui = UI[lang]
    first = items[0]
    name = _category_name(first, lang)
    path = f'{ui["prefix"]}/problems/{first["catalog_slug"]}/'
    alternates = {code: f'{UI[code]["prefix"]}/problems/{first["catalog_slug"]}/' for code in LANGS if code in have}
    groups: dict[str, list[tuple[str, str]]] = {}
    # A whole thing with a page of its own sits under its make or brand, as a chip...
    for entry in items:
        if entry["group"]:
            groups.setdefault(entry["group"], []).append((entry["label"], _chip(entry, lang)))
    # ...and a part is reached through each whole thing it is fitted to, one line for each.
    fitted: dict[str, list[dict]] = {}
    for entry in items:
        for product in entry["products"]:
            fitted.setdefault(product, []).append(entry)
    for product, parts in fitted.items():
        group = first["groups"].get(product) or ui["hub_other"]
        links = ", ".join(f'<a href="{ui["prefix"]}/problems/{p["slug"]}/">{_e(p["label"])}</a>'
                          for p in sorted(parts, key=lambda p: p["label"]))
        groups.setdefault(group, []).append((product, f"<li><strong>{_e(product)}</strong>: {links}</li>"))
    placed = {e["slug"] for e in items if e["group"] or e["products"]} | {p["slug"] for ps in fitted.values() for p in ps}
    for entry in items:
        if entry["slug"] not in placed:
            groups.setdefault(ui["hub_other"], []).append((entry["label"], _chip(entry, lang)))
    sections = []
    for group, rows in sorted(groups.items()):
        rows.sort()
        kind = "chips" if all(row.startswith("<li><a") for _, row in rows) else "rows"
        opened = " open" if len(rows) <= OPEN_UP_TO else ""
        sections.append(f'      <details class="group"{opened}><summary>{_e(group)}<span>{_e(ui["products"].format(n=len(rows)))}</span></summary>\n'
                        f'      <ul class="{kind}">{"".join(row for _, row in rows)}</ul></details>')
    body = (f'      <p class="crumb"><a href="{ui["prefix"]}/problems/">{_e(ui["crumb"])}</a></p>\n'
            f'      <h1>{_e(ui["cat_title"].format(name=name))}</h1>\n'
            f'      <p class="lead">{_e(ui["cat_lead"].format(n=len(items)))}</p>\n'
            + "\n".join(sections) + "\n"
            f'      <div class="short"><h2>{_e(ui["cta_h"])}</h2><p>{_e(ui["cta_p"])}</p>'
            f'<p><a class="button" href="{ui["get"]}">{_e(ui["cta_b"])}</a></p></div>\n'
            f'      <p class="fine">{_e(ui["note"])}</p>')
    return _chrome(lang, title=ui["cat_title"].format(name=name), description=ui["cat_desc"].format(n=len(items), name=name),
                   path=path, alternates=alternates, depth=3 if lang == "tr" else 2, css=css, body=body)


def _hub_page(lang: str, entries: list[dict], css: str) -> str:
    """The front door: one card for each catalog, with what it holds."""
    ui = UI[lang]
    path = f'{ui["prefix"]}/problems/'
    alternates = {code: f'{UI[code]["prefix"]}/problems/' for code in LANGS}
    by_catalog: dict[str, list[dict]] = {}
    for entry in entries:
        by_catalog.setdefault(entry["catalog_slug"], []).append(entry)
    cards = []
    for slug, items in sorted(by_catalog.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        reports = sum(e["counts"][lang] for e in items)
        best = sorted(items, key=lambda e: (-e["counts"][lang], e["label"]))[:3]
        cards.append(
            f'<li><a class="card" href="{ui["prefix"]}/problems/{slug}/"><strong>{_e(_category_name(items[0], lang))}</strong>'
            f'<span>{_e(ui["products"].format(n=len(items)))} · {_e(ui["reports"].format(n=reports))}</span>'
            f'<small>{_e(", ".join(e["label"] for e in best))}…</small></a></li>')
    body = (f'      <h1>{_e(ui["hub_title"])}</h1>\n      <p class="lead">{_e(ui["hub_lead"])}</p>\n'
            f'      <ul class="cards">{"".join(cards)}</ul>\n'
            f'      <div class="short"><h2>{_e(ui["cta_h"])}</h2><p>{_e(ui["cta_p"])}</p>'
            f'<p><a class="button" href="{ui["get"]}">{_e(ui["cta_b"])}</a></p></div>\n'
            f'      <p class="fine">{_e(ui["note"])}</p>')
    return _chrome(lang, title=ui["hub_title"], description=ui["hub_desc"], path=path, alternates=alternates,
                   depth=2 if lang == "tr" else 1, css=css, body=body)


def _sitemap(pages: list[tuple[str, dict[str, str]]]) -> str:
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">']
    for path, alternates in pages:
        out.append("  <url>")
        out.append(f"    <loc>{ORIGIN}{path}</loc>")
        for code, url in alternates.items():
            out.append(f'    <xhtml:link rel="alternate" hreflang="{code}" href="{ORIGIN}{url}"/>')
        if alternates:
            default = alternates.get("en") or next(iter(alternates.values()))
            out.append(f'    <xhtml:link rel="alternate" hreflang="x-default" href="{ORIGIN}{default}"/>')
        out.append("  </url>")
    out.append("</urlset>")
    return "\n".join(out) + "\n"


def render(packs_dir: Path, site_dir: Path) -> list[str]:
    """Rewrite the generated pages under `site_dir`; returns every address written."""
    css = stylesheet_hash(site_dir)
    records: list[tuple[dict, dict, dict, dict]] = []  # (catalog, entry, subject, claims by language)
    slugs: set[str] = set()
    with tempfile.TemporaryDirectory() as scratch:
        for root, manifest in real_catalogs(packs_dir):
            catalog = read_catalog(build_catalog(root, Path(scratch) / f"{root.name}.kpack"))
            languages = [code for code in LANGS if code in manifest.get("languages", LANGS)]
            catalog_slug = slugify(catalog["name"])
            slugs.add(catalog_slug)  # a catalog's own page keeps its address; a product never takes it
            for subject in sorted(catalog["subjects"].values(), key=lambda s: (s["label"], s["kind"])):
                per_lang = {code: _subject_claims(subject, code) for code in languages}
                have = {code for code, picked in per_lang.items() if len(picked) >= MIN_CLAIMS}
                if not have:
                    continue
                slug = base = slugify(subject["label"])
                while slug in slugs:
                    slug = f"{base}-{len(slugs)}"
                slugs.add(slug)
                entry = {"slug": slug, "label": subject["label"], "products": sorted(set(subject["products"])),
                         "catalog": catalog["name"], "catalog_slug": catalog_slug, "names": catalog["names"],
                         "group": subject["group"], "groups": catalog["groups"],
                         "counts": {code: len(per_lang[code]) for code in languages}, "have": have}
                records.append((catalog, entry, subject, per_lang))
    entries = [entry for _, entry, _, _ in records]
    written: dict[str, str] = {}
    for catalog, entry, subject, per_lang in records:
        for code in entry["have"]:
            written[f'{UI[code]["prefix"]}/problems/{entry["slug"]}/'] = _subject_page(
                catalog, entry, subject, code, per_lang[code], css, entries)
    by_catalog: dict[str, list[dict]] = {}
    for entry in entries:
        by_catalog.setdefault(entry["catalog_slug"], []).append(entry)
    for slug, items in by_catalog.items():
        have = {code for entry in items for code in entry["have"]}
        for code in have:
            written[f'{UI[code]["prefix"]}/problems/{slug}/'] = _category_page(
                code, [e for e in items if code in e["have"]], css, have)
    for code in LANGS:
        shown = [e for e in entries if code in e["have"]]
        if shown:
            written[f'{UI[code]["prefix"]}/problems/'] = _hub_page(code, shown, css)

    for tree in (site_dir / "problems", site_dir / "tr" / "problems"):
        if tree.exists():
            shutil.rmtree(tree)
    sitemap_file = site_dir / "sitemap-problems.xml"
    if not written:
        sitemap_file.unlink(missing_ok=True)
        return []
    for path, text in written.items():
        target = site_dir / path.strip("/") / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    pages = []
    for path in sorted(written):
        tail = path.removeprefix("/tr") if path.startswith("/tr/") else path
        alternates = {code: f'{UI[code]["prefix"]}{tail}' for code in LANGS if f'{UI[code]["prefix"]}{tail}' in written}
        pages.append((path, alternates))
    with open(sitemap_file, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(_sitemap(pages))
    return sorted(written)


def main() -> int:
    here = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--packs", type=Path, default=here / "packs")
    parser.add_argument("--site", type=Path, default=here / "site")
    args = parser.parse_args()
    written = render(args.packs, args.site)
    print(f"wrote {len(written)} pages under {args.site}")
    return 0 if written else 1


if __name__ == "__main__":
    sys.exit(main())
