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
import json
import re
import shutil
import sqlite3
import sys
import tempfile
import tomllib
import zlib
from pathlib import Path
from urllib.parse import quote

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
        "locale": "en_US",
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
        "safety": "Safety risk",
        "serious_h": "Safety first",
        "serious_lead": "Reports of a product catching fire, exploding or shocking its owner, each linked to the page it came from.",
        "serious_in": "Safety first in {name}",
        "safety_note": "{n} of these reports describe a fire, explosion or shock risk.",
        "title": "{label}: known problems",
        "title_risk": "{label}: known problems and safety risks",
        "safety_title": "Product fires, explosions and shocks: reports by product",
        "safety_desc": "Sourced reports of products catching fire, exploding or shocking their owners, with the page each one came from.",
        "safety_lead": "Every product in the catalogs with a serious report of it catching fire, exploding or shocking its owner. Each links to the report on the product's page, and from there to the page it came from.",
        "safety_all": "All {n} products with safety reports",
        "sponsored": "Sponsored",
        "sponsored_note": "A paid placement. It is not a finding, and it changes nothing reported on this page.",
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
        "phone_p": "Reading this on a phone? Kriko runs on a Windows computer.",
        "phone_a": "Email yourself the link",
        "phone_subject": "Kriko for my computer",
        "note": "These reports come from the pages linked under each item: owner forums, repair guides and workshops. They are not a diagnosis of any one unit, and a careful check of the one you are buying still applies.",
        "licence": "Text from the Kriko {name} catalog, version {version}, under the {license} license.",
        "hub_title": "Known problems, by product and part",
        "hub_lead": "Pick a category. Each product page lists what owners and repairers report going wrong with it, every report linked to the page it came from.",
        "hub_desc": "Sourced known problems for specific products and parts, with what to check before you buy.",
        "hub_other": "Other",
        "reports": "{n} reports",
        "show_more": "Show {n} more",
        "footer_home": "kriko.cc",
        "footer_help": "Help and feedback",
        "privacy": "Privacy",
    },
    "tr": {
        "html_lang": "tr",
        "locale": "tr_TR",
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
        "safety": "Güvenlik riski",
        "serious_h": "Önce güvenlik",
        "serious_lead": "Bir ürünün yangın çıkardığı, patladığı ya da sahibini çarptığı raporlar; her biri geldiği sayfaya bağlantı verir.",
        "serious_in": "{name} için önce güvenlik",
        "safety_note": "Bu raporlardan {n} tanesi yangın, patlama ya da elektrik çarpması riski bildiriyor.",
        "title": "{label} sorunları ve bilinen arızalar",
        "title_risk": "{label} sorunları ve güvenlik riskleri",
        "safety_title": "Yangın, patlama ve elektrik çarpması: ürün bazında raporlar",
        "safety_desc": "Ürünlerin yangın çıkardığı, patladığı ya da sahibini çarptığı kaynaklı raporlar; her biri geldiği sayfaya bağlantı verir.",
        "safety_lead": "Yangın çıkardığı, patladığı ya da sahibini çarptığı ciddi biçimde bildirilen her ürün. Her biri, ürünün sayfasındaki rapora, oradan da geldiği sayfaya bağlantı verir.",
        "safety_all": "Güvenlik raporu olan {n} ürünün tümü",
        "sponsored": "Sponsorlu",
        "sponsored_note": "Ücretli bir yerleşimdir. Bir bulgu değildir ve bu sayfada bildirilen hiçbir şeyi değiştirmez.",
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
        "phone_p": "Bunu telefondan mı okuyorsunuz? Kriko bir Windows bilgisayarda çalışır.",
        "phone_a": "Bağlantıyı kendinize e-postalayın",
        "phone_subject": "Kriko'yu bilgisayarıma kuracağım",
        "note": "Bu maddeler, her birinin altında bağlantısı verilen sayfalardan derlenmiştir: kullanıcı forumları, onarım rehberleri ve servisler. Belirli bir ürünün teşhisi değildir; satın alacağınız ürünü dikkatle kontrol etmeniz yine de gerekir.",
        "licence": "Metin, Kriko {name} kataloğundan (sürüm {version}) alınmıştır, {license} lisansıyla.",
        "hub_title": "Bilinen sorunlar: ürün ve parça bazında",
        "hub_lead": "Bir kategori seçin. Her ürün sayfası, sahiplerin ve tamircilerin neyin bozulduğunu bildirdiğini listeler; her rapor, geldiği sayfaya bağlantı verir.",
        "hub_desc": "Belirli ürün ve parçalar için kaynaklı bilinen sorunlar ve satın almadan önce neye bakılacağı.",
        "hub_other": "Diğer",
        "reports": "{n} rapor",
        "show_more": "{n} tane daha göster",
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


# A closed set of 24x24 line drawings. A catalog picks one by name in `[pack] icon`; an unknown
# name, or none, is the box. The severity of a claim and a safety risk each have their own.
ICONS = {
    "box": '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><path d="M3.3 7 12 12l8.7-5M12 22V12"/>',
    "car": '<path d="M19 17h2c.6 0 1-.4 1-1v-3c0-.9-.7-1.7-1.5-1.9C18.7 10.6 16 10 16 10s-1.3-1.4-2.2-2.3c-.5-.4-1.1-.7-1.8-.7H5c-.6 0-1.1.4-1.4.9l-1.4 2.9A3.7 3.7 0 0 0 2 12v4c0 .6.4 1 1 1h2"/><circle cx="7" cy="17" r="2"/><path d="M9 17h6"/><circle cx="17" cy="17" r="2"/>',
    "phone": '<rect x="5" y="2" width="14" height="20" rx="2"/><path d="M12 18h.01"/>',
    "laptop": '<path d="M20 16V7a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v9m16 0H4m16 0 1.3 2.6a1 1 0 0 1-.9 1.4H3.6a1 1 0 0 1-.9-1.4L4 16"/>',
    "tablet": '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M12 18h.01"/>',
    "tv": '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
    "gamepad": '<path d="M6 11h4M8 9v4M15 12h.01M18 10h.01"/><path d="M17.3 5H6.7a4 4 0 0 0-4 3.6C2.6 9.4 2 14.5 2 16a3 3 0 0 0 3 3c1 0 1.5-.5 2-1l1.4-1.4a2 2 0 0 1 1.4-.6h4.4a2 2 0 0 1 1.4.6L17 18c.5.5 1 1 2 1a3 3 0 0 0 3-3c0-1.5-.6-6.6-.7-7.4A4 4 0 0 0 17.3 5z"/>',
    "headphones": '<path d="M3 18v-6a9 9 0 0 1 18 0v6"/><path d="M21 19a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3zM3 19a2 2 0 0 0 2 2h1a2 2 0 0 0 2-2v-3a2 2 0 0 0-2-2H3z"/>',
    "watch": '<circle cx="12" cy="12" r="6"/><path d="M12 10v2l1 1M16.1 7.7l-.8-4.1a2 2 0 0 0-2-1.6h-2.6a2 2 0 0 0-2 1.6l-.8 4.1m.1 8.6.8 4.1a2 2 0 0 0 2 1.6h2.6a2 2 0 0 0 2-1.6l.8-4.1"/>',
    "printer": '<path d="M6 9V2h12v7"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/>',
    "drone": '<circle cx="5" cy="5" r="2.5"/><circle cx="19" cy="5" r="2.5"/><circle cx="5" cy="19" r="2.5"/><circle cx="19" cy="19" r="2.5"/><rect x="9" y="9" width="6" height="6" rx="1"/><path d="m7 7 2 2M17 7l-2 2M7 17l2-2M17 17l-2-2"/>',
    "chip": '<rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>',
    "monitor": '<rect x="2" y="3" width="20" height="13" rx="2"/><path d="M8 21h8M12 16v5"/>',
    "bike": '<circle cx="18.5" cy="17.5" r="3.5"/><circle cx="5.5" cy="17.5" r="3.5"/><circle cx="15" cy="5" r="1"/><path d="M12 17.5V14l-3-3 4-3 2 3h2"/>',
    "scooter": '<circle cx="6" cy="18" r="2.5"/><circle cx="19" cy="18" r="2.5"/><path d="M8.5 18H16.5M18 15.5 15 4h-3M6 4h3"/>',
    "battery": '<rect x="2" y="7" width="16" height="10" rx="2"/><path d="M22 11v2M6 10v4M10 10v4"/>',
    "coffee": '<path d="M18 8h1a4 4 0 0 1 0 8h-1"/><path d="M2 8h16v9a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4V8z"/><path d="M6 1v3M10 1v3M14 1v3"/>',
    "washer": '<rect x="3" y="2" width="18" height="20" rx="2"/><circle cx="12" cy="13" r="5"/><path d="M7 6h.01M11 6h.01"/>',
    "fridge": '<rect x="5" y="2" width="14" height="20" rx="2"/><path d="M5 10h14M9 6v1M9 13v3"/>',
    "vacuum": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3"/><path d="M12 3v2"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "flame": '<path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.4-.5-2-1-3-1.1-2.1-.2-4 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.2.4-2.3 1-3a2.5 2.5 0 0 0 2.5 2.5z"/>',
    "alert": '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/>',
    "wrench": '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.8-3.8a6 6 0 0 1-7.9 7.9l-6.9 6.9a2.1 2.1 0 0 1-3-3l6.9-6.9a6 6 0 0 1 7.9-7.9l-3.8 3.8z"/>',
    "info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
}
SEVERITY_ICON = {"high": "alert", "medium": "wrench", "low": "info"}
# What makes a claim a safety risk, whatever the product: it can start a fire, explode or shock a
# person. Not a fault that merely annoys, nor one that is only dangerous in a long chain. Matched
# on the claim's English title alone, so it is flagged the same way in every language it is shown
# in, and a body that mentions a fire in passing does not make a piston ring a hazard.
HAZARD = re.compile(
    r"\b(?:fires?(?! (?:hd|tv|stick|max|kids|tablet|os|\d))|flames?|burst into flames|explo(?:de|des|ded|ding|sion|sions)"
    r"|electrocut\w*|electric shock)\b", re.I)
SAFETY_FIRST = 12  # claims featured on the hub, and 3 on a catalog's page
SAFETY_SHOWN = 5  # of them, how many are in view before "show more"


def icon(name: str, cls: str = "ico") -> str:
    return (f'<svg class="{cls}" viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">{ICONS.get(name, ICONS["box"])}</svg>')


def is_hazard(claim: dict) -> bool:
    text = claim["text"].get("en") or next(iter(claim["text"].values()), {"title": ""})
    return bool(HAZARD.search(text["title"]))


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
        picture = str((declared.get("pack") or {}).get("icon") or "box")
        subjects = {sid: {"label": label, "kind": kind, "claims": [], "products": [], "group": ""}
                    for sid, label, kind in conn.execute("SELECT subject_id, label, kind FROM subjects")}
        sources: dict[str, list[tuple[str, str]]] = {}
        seen: dict[str, str] = {}  # the day a claim's newest source was read, which is when the claim was last checked
        for claim_id, url, domain, when in conn.execute(
            "SELECT e.claim_id, s.url, s.domain, s.retrieved_at FROM evidence e JOIN sources s USING (source_id) ORDER BY s.url"
        ):
            sources.setdefault(claim_id, []).append((url, domain))
            day = str(when or "")[:10]
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) and day > seen.get(claim_id, ""):
                seen[claim_id] = day
        claims = {}
        for claim_id, subject_id, severity, detection in conn.execute(
            "SELECT claim_id, subject_id, severity, detection FROM claims"
        ):
            claims[claim_id] = {"id": claim_id, "severity": severity, "detection": detection, "seen": seen.get(claim_id, ""),
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
        return {"name": name, "names": declared.get("names") or {}, "icon": picture if picture in ICONS else "box",
                "version": version, "license": license_,
                "subjects": subjects, "groups": groups}
    finally:
        conn.close()


def _e(text) -> str:
    return html.escape(str(text), quote=True)


def _handoff(ui: dict) -> str:
    """A mailto: link that sends the reader the install page, for a phone that cannot run Kriko.

    Plain HTML on purpose: these pages run no script, and the site sends nothing anywhere."""
    return _e(f'mailto:?subject={quote(ui["phone_subject"])}&body={quote(ORIGIN + ui["get"], safe="")}')


def _cta(ui: dict) -> str:
    """The closing call to action of every page. `.handoff` shows on touch screens only (styles.css)."""
    return (f'<div class="short"><h2>{_e(ui["cta_h"])}</h2><p>{_e(ui["cta_p"])}</p>'
            f'<p><a class="button" href="{ui["get"]}">{_e(ui["cta_b"])}</a></p>'
            f'<p class="handoff">{_e(ui["phone_p"])} <a href="{_handoff(ui)}">{_e(ui["phone_a"])}</a></p></div>')


ORGANISATION = {"@type": "Organization", "name": "Kriko", "url": f"{ORIGIN}/"}


def _breadcrumbs(trail: list[tuple[str, str]]) -> dict:
    """schema.org breadcrumbs, so a result can show the path to the page instead of a bare address."""
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [{"@type": "ListItem", "position": n, "name": name, "item": f"{ORIGIN}{path}"}
                                for n, (name, path) in enumerate(trail, 1)]}


def _article(lang: str, *, headline: str, description: str, path: str, modified: str) -> dict:
    page = {"@context": "https://schema.org", "@type": "Article", "headline": headline, "description": description,
            "inLanguage": UI[lang]["html_lang"], "mainEntityOfPage": f"{ORIGIN}{path}",
            "image": f"{ORIGIN}/assets/share-card.jpg", "author": ORGANISATION, "publisher": ORGANISATION}
    if modified:
        page["dateModified"] = modified
    return page


def _collection(lang: str, *, name: str, description: str, path: str, items: list[tuple[str, str]]) -> dict:
    """schema.org for a page that is a list of other pages: what the list holds, and where each one is."""
    return {"@context": "https://schema.org", "@type": "CollectionPage", "name": name, "description": description,
            "inLanguage": UI[lang]["html_lang"], "url": f"{ORIGIN}{path}", "isPartOf": {"@type": "WebSite", "name": "Kriko", "url": f"{ORIGIN}/"},
            "mainEntity": {"@type": "ItemList", "numberOfItems": len(items),
                           "itemListElement": [{"@type": "ListItem", "position": n, "name": label, "url": f"{ORIGIN}{url}"}
                                               for n, (label, url) in enumerate(items, 1)]}}


def _structured(data: dict) -> str:
    """One block of structured data. It is data, not code: nothing in it can close the tag it sits in."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f'  <script type="application/ld+json">{text}</script>\n'


def _updated(claims: list[dict]) -> str:
    """The day the newest source behind any of `claims` was read; empty when none says."""
    return max((c["seen"] for c in claims), default="")


def load_sponsors(site_dir: Path) -> list[dict]:
    """The paid placements `site/sponsors.json` lists that can be shown, by id.

    A placement is a link to an https address, with a name and a sentence in each language it
    is shown in. One that is not is left out and named on stderr: no advertisement is better
    than one that cannot be told from a finding, or that links somewhere a visitor cannot trust.
    """
    path = site_dir / "sponsors.json"
    if not path.is_file():
        return []
    kept: dict[str, dict] = {}
    for row in json.loads(path.read_text(encoding="utf-8")):
        ident = str(row.get("id", ""))
        if ident and ident not in kept and str(row.get("url", "")).startswith("https://") \
                and isinstance(row.get("name"), dict) and isinstance(row.get("text"), dict):
            kept[ident] = row
        else:
            print(f"sponsors.json: {ident or row} is not a placement that can be shown", file=sys.stderr)
    return [kept[ident] for ident in sorted(kept)]


def _sponsored(lang: str, sponsors: list[dict], catalog_slug: str) -> str:
    """The one paid placement for a page of this catalog, boxed apart from the findings and labelled as paid."""
    ui = UI[lang]
    for row in sponsors:
        if lang in row["name"] and lang in row["text"] and (not row.get("catalogs") or catalog_slug in row["catalogs"]):
            return (f'      <aside class="sponsored" aria-label="{_e(ui["sponsored"])}"><p class="tag">{_e(ui["sponsored"])}</p>'
                    f'<p><a href="{_e(row["url"])}" rel="sponsored nofollow noopener">{_e(row["name"][lang])}</a>: '
                    f'{_e(row["text"][lang])}</p><p class="fine">{_e(ui["sponsored_note"])}</p></aside>\n')
    return ""


def _chrome(lang: str, *, title: str, description: str, path: str, alternates: dict[str, str], depth: int,
            css: str, body: str, schema: tuple = ()) -> str:
    ui = UI[lang]
    up = "../" * depth
    data = "".join(_structured(one) for one in schema)
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
  <meta name="robots" content="index, follow, max-image-preview:large, max-snippet:-1">
  <link rel="icon" href="{up}assets/icon-32.png">
  <link rel="stylesheet" href="{up}styles.css?v={css}">
  <link rel="canonical" href="{ORIGIN}{path}">
{links}  <meta property="og:type" content="article">
  <meta property="og:site_name" content="Kriko">
  <meta property="og:locale" content="{ui["locale"]}">
  <meta property="og:title" content="{_e(title)}">
  <meta property="og:description" content="{_e(description)}">
  <meta property="og:url" content="{ORIGIN}{path}">
  <meta property="og:image" content="{ORIGIN}/assets/share-card.jpg">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{_e(title)}">
  <meta name="twitter:description" content="{_e(description)}">
{data}</head>
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
             f'        <h3>{icon(SEVERITY_ICON[severity])}{_e(text["title"])}</h3>']
    tags = []
    if is_hazard(claim):
        tags.append(f'<strong class="hazard">{icon("flame")}{_e(ui["safety"])}</strong>')
    if detect:
        tags.append(_e(detect))
    if tags:
        parts.append(f'        <p class="how">{" · ".join(tags)}</p>')
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
                  entries: list[dict], sponsors: list[dict]) -> str:
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
            sections.append(f'      <h2>{icon(SEVERITY_ICON[severity])}{_e(ui["group"][severity])}</h2>\n'
                            + "\n".join(_claim_html(c, lang) for c in group))
    glance = ""
    if len(claims) >= GLANCE_FROM:
        items = "".join(
            f'<li class="sev-{c["severity"] if c["severity"] in SEVERITY_ORDER else "low"}">'
            f'{icon("flame" if is_hazard(c) else SEVERITY_ICON.get(c["severity"], "info"))}'
            f'<a href="#c-{_e(c["id"][:8])}">{_e(c["text"][lang]["title"])}</a></li>' for c in claims)
        glance = f'      <nav class="glance" aria-label="{_e(ui["glance"])}"><h2>{_e(ui["glance"])}</h2><ul>{items}</ul></nav>\n'
    fits = ""
    if subject["products"]:
        items = "".join(f"<li>{_e(p)}</li>" for p in sorted(set(subject["products"])))
        fits = f'      <h2>{_e(ui["fits"])}</h2>\n      <ul>{items}</ul>\n'
    risky = sum(1 for c in claims if is_hazard(c))
    risk = (f'      <p class="alert">{icon("flame")}{_e(ui["safety_note"].format(n=risky))}</p>\n') if risky else ""
    near = _neighbours(entry, entries, lang)
    more = ""
    if near:
        chips = "".join(_chip(e, lang) for e in near)
        more = (f'      <h2>{_e(ui["more"].format(category=category))}</h2>\n      <ul class="chips">{chips}</ul>\n'
                f'      <p><a href="{ui["prefix"]}/problems/{entry["catalog_slug"]}/">{_e(ui["all_in"].format(category=category))}</a></p>\n')
    body = (f'      <p class="crumb"><a href="{ui["prefix"]}/problems/">{_e(ui["crumb"])}</a> › '
            f'<a href="{ui["prefix"]}/problems/{entry["catalog_slug"]}/">{_e(category)}</a></p>\n'
            f'      <h1>{icon(entry["icon"], "ico big")}{_e(ui["title"].format(label=label))}</h1>\n'
            f'      <p class="lead">{_e(ui["lead"].format(n=len(claims)))}</p>\n'
            + risk + glance + "\n".join(sections) + "\n" + fits + _sponsored(lang, sponsors, entry["catalog_slug"]) + more +
            f'      {_cta(ui)}\n'
            f'      <p class="fine">{_e(ui["note"])}</p>\n'
            f'      <p class="fine">{_e(ui["licence"].format(name=catalog["name"], version=catalog["version"], license=catalog["license"]))}</p>')
    description = ui["desc"].format(label=label, n=len(claims), top=top)
    description = description if len(description) <= 158 else description[:155].rsplit(" ", 1)[0] + "…"
    # A page that reports a fire says so in its title: that is the word a reader searches for.
    title = ui["title_risk" if risky else "title"].format(label=label)
    schema = (_breadcrumbs([(ui["crumb"], f'{ui["prefix"]}/problems/'),
                            (category, f'{ui["prefix"]}/problems/{entry["catalog_slug"]}/'), (label, path)]),
              _article(lang, headline=title, description=description, path=path, modified=_updated(claims)))
    return _chrome(lang, title=title, description=description, path=path,
                   alternates=alternates, depth=3 if lang == "tr" else 2, css=css, body=body, schema=schema)


def _safety_rows(lang: str, entries: list[dict]) -> list[tuple[dict, dict, int]]:
    """The worst safety report of each product of `entries` that has one, as (product, report, how many), worst first.

    A product with more serious reports of the kind leads, then the one more sites agree on, so a fire
    several pages agree on outranks one a single page reports; the report shown is the best backed.
    """
    found = []
    for entry in entries:
        risky = [c for c in entry["claims"].get(lang, []) if is_hazard(c)]
        high = [c for c in risky if c["severity"] == "high"]
        if high:
            best = min(high, key=lambda c: (-len(c["sources"]), c["id"]))
            sites = len({domain or url for c in risky for url, domain in c["sources"]})
            found.append((-len(high), -sites, entry["label"], entry, best, len(risky)))
    return [(entry, claim, count) for *_, entry, claim, count in sorted(found, key=lambda f: f[:3])]


def _alert_row(lang: str, entry: dict, claim: dict, count: int) -> str:
    ui = UI[lang]
    more = f' · {_e(ui["reports"].format(n=count))}' if count > 1 else ""
    return (f'<li><a href="{ui["prefix"]}/problems/{entry["slug"]}/#c-{_e(claim["id"][:8])}">{icon("flame")}'
            f'<span>{_e(claim["text"][lang]["title"])}<small>{_e(entry["label"])}{more}</small></span></a></li>')


def _safety_first(lang: str, entries: list[dict], heading: str, limit: int, everything: bool = False) -> str:
    """The worst safety reports of `entries`, one for each product, each linked to its own card.

    `everything` ends the strip with a link to the page that lists every one of them.
    """
    ui = UI[lang]
    found = _safety_rows(lang, entries)
    if not found:
        return ""
    rows = [_alert_row(lang, *row) for row in found[:limit]]
    # The first few stay in view, so the categories below are not pushed off the screen; the rest open on request.
    rest = (f'<details class="rest"><summary>{_e(ui["show_more"].format(n=len(rows) - SAFETY_SHOWN))}</summary>'
            f'<ul class="alerts">{"".join(rows[SAFETY_SHOWN:])}</ul></details>') if len(rows) > SAFETY_SHOWN else ""
    every = (f'<p class="all"><a href="{ui["prefix"]}/problems/safety/">{_e(ui["safety_all"].format(n=len(found)))}</a></p>'
             if everything else "")
    return (f'      <section class="serious"><h2>{icon("flame")}{_e(heading)}</h2>\n'
            f'      <p>{_e(ui["serious_lead"])}</p>\n      <ul class="alerts">{"".join(rows[:SAFETY_SHOWN])}</ul>{rest}{every}</section>\n')


def _safety_page(lang: str, entries: list[dict], css: str, have: set[str]) -> str:
    """Every product with a serious fire, explosion or shock report, under its catalog: the page a search for one lands on."""
    ui = UI[lang]
    path = f'{ui["prefix"]}/problems/safety/'
    alternates = {code: f'{UI[code]["prefix"]}/problems/safety/' for code in LANGS if code in have}
    found = _safety_rows(lang, entries)
    by_catalog: dict[str, list[tuple[dict, dict, int]]] = {}
    for row in found:
        by_catalog.setdefault(row[0]["catalog_slug"], []).append(row)
    sections = ""
    for slug, rows in sorted(by_catalog.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        first = rows[0][0]
        sections += (f'      <h2>{icon(first["icon"])}<a href="{ui["prefix"]}/problems/{slug}/">{_e(_category_name(first, lang))}</a></h2>\n'
                     f'      <ul class="alerts">{"".join(_alert_row(lang, *row) for row in rows)}</ul>\n')
    body = (f'      <p class="crumb"><a href="{ui["prefix"]}/problems/">{_e(ui["crumb"])}</a></p>\n'
            f'      <h1>{icon("flame", "ico big hazard")}{_e(ui["safety_title"])}</h1>\n      <p class="lead">{_e(ui["safety_lead"])}</p>\n'
            f'      <section class="serious">\n{sections}      </section>\n'
            f'      {_cta(ui)}\n'
            f'      <p class="fine">{_e(ui["note"])}</p>')
    schema = (_breadcrumbs([(ui["crumb"], f'{ui["prefix"]}/problems/'), (ui["safety_title"], path)]),
              _collection(lang, name=ui["safety_title"], description=ui["safety_desc"], path=path,
                          items=[(e["label"], f'{ui["prefix"]}/problems/{e["slug"]}/') for e, _, _ in found]))
    return _chrome(lang, title=ui["safety_title"], description=ui["safety_desc"], path=path, alternates=alternates,
                   depth=3 if lang == "tr" else 2, css=css, body=body, schema=schema)


def _category_page(lang: str, items: list[dict], css: str, have: set[str], sponsors: list[dict]) -> str:
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
            f'      <h1>{icon(first["icon"], "ico big")}{_e(ui["cat_title"].format(name=name))}</h1>\n'
            f'      <p class="lead">{_e(ui["cat_lead"].format(n=len(items)))}</p>\n'
            + _safety_first(lang, items, ui["serious_in"].format(name=name), 3)
            + "\n".join(sections) + "\n" + _sponsored(lang, sponsors, first["catalog_slug"]) +
            f'      {_cta(ui)}\n'
            f'      <p class="fine">{_e(ui["note"])}</p>')
    title, description = ui["cat_title"].format(name=name), ui["cat_desc"].format(n=len(items), name=name)
    schema = (_breadcrumbs([(ui["crumb"], f'{ui["prefix"]}/problems/'), (name, path)]),
              _collection(lang, name=title, description=description, path=path,
                          items=[(e["label"], f'{ui["prefix"]}/problems/{e["slug"]}/') for e in sorted(items, key=lambda e: e["label"])]))
    return _chrome(lang, title=title, description=description, path=path, alternates=alternates,
                   depth=3 if lang == "tr" else 2, css=css, body=body, schema=schema)


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
            f'<li><a class="card" href="{ui["prefix"]}/problems/{slug}/">{icon(items[0]["icon"], "ico big")}<strong>{_e(_category_name(items[0], lang))}</strong>'
            f'<span>{_e(ui["products"].format(n=len(items)))} · {_e(ui["reports"].format(n=reports))}</span>'
            f'<small>{_e(", ".join(e["label"] for e in best))}…</small></a></li>')
    body = (f'      <h1>{_e(ui["hub_title"])}</h1>\n      <p class="lead">{_e(ui["hub_lead"])}</p>\n'
            + _safety_first(lang, entries, ui["serious_h"], SAFETY_FIRST, everything=True) +
            f'      <ul class="cards">{"".join(cards)}</ul>\n'
            f'      {_cta(ui)}\n'
            f'      <p class="fine">{_e(ui["note"])}</p>')
    schema = (_collection(lang, name=ui["hub_title"], description=ui["hub_desc"], path=path,
                          items=[(_category_name(items[0], lang), f'{ui["prefix"]}/problems/{slug}/')
                                 for slug, items in sorted(by_catalog.items())]),)
    return _chrome(lang, title=ui["hub_title"], description=ui["hub_desc"], path=path, alternates=alternates,
                   depth=2 if lang == "tr" else 1, css=css, body=body, schema=schema)


def _sitemap(pages: list[tuple[str, dict[str, str], str]]) -> str:
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">']
    for path, alternates, modified in pages:
        out.append("  <url>")
        out.append(f"    <loc>{ORIGIN}{path}</loc>")
        if modified:
            out.append(f"    <lastmod>{modified}</lastmod>")
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
    sponsors = load_sponsors(site_dir)
    records: list[tuple[dict, dict, dict, dict]] = []  # (catalog, entry, subject, claims by language)
    slugs: set[str] = {"safety"}  # the page of every safety report keeps its address; a product never takes it
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
                # A name already taken gets a number drawn from the product itself, never from how many
                # pages came first: a page that has been indexed must not move because a catalog was added.
                number = 100 + zlib.crc32(f"{catalog_slug}/{subject['label']}/{subject['kind']}".encode()) % 900
                while slug in slugs:
                    slug = f"{base}-{number}"
                    number += 1
                slugs.add(slug)
                entry = {"slug": slug, "label": subject["label"], "products": sorted(set(subject["products"])),
                         "catalog": catalog["name"], "catalog_slug": catalog_slug, "names": catalog["names"],
                         "group": subject["group"], "groups": catalog["groups"], "icon": catalog["icon"],
                         "claims": per_lang,
                         "counts": {code: len(per_lang[code]) for code in languages}, "have": have,
                         "updated": {code: _updated(per_lang[code]) for code in languages}}
                records.append((catalog, entry, subject, per_lang))
    entries = [entry for _, entry, _, _ in records]
    written: dict[str, str] = {}
    modified: dict[str, str] = {}  # the day each page was last checked, for the sitemap
    for catalog, entry, subject, per_lang in records:
        for code in entry["have"]:
            path = f'{UI[code]["prefix"]}/problems/{entry["slug"]}/'
            written[path] = _subject_page(catalog, entry, subject, code, per_lang[code], css, entries, sponsors)
            modified[path] = entry["updated"][code]
    by_catalog: dict[str, list[dict]] = {}
    for entry in entries:
        by_catalog.setdefault(entry["catalog_slug"], []).append(entry)
    for slug, items in by_catalog.items():
        have = {code for entry in items for code in entry["have"]}
        for code in have:
            shown = [e for e in items if code in e["have"]]
            path = f'{UI[code]["prefix"]}/problems/{slug}/'
            written[path] = _category_page(code, shown, css, have, sponsors)
            modified[path] = max(e["updated"][code] for e in shown)
    safety = {code for code in LANGS if _safety_rows(code, [e for e in entries if code in e["have"]])}
    for code in LANGS:
        shown = [e for e in entries if code in e["have"]]
        if shown:
            written[f'{UI[code]["prefix"]}/problems/'] = _hub_page(code, shown, css)
            modified[f'{UI[code]["prefix"]}/problems/'] = max(e["updated"][code] for e in shown)
        if code in safety:
            written[f'{UI[code]["prefix"]}/problems/safety/'] = _safety_page(code, shown, css, safety)
            modified[f'{UI[code]["prefix"]}/problems/safety/'] = max(e["updated"][code] for e in shown)

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
        pages.append((path, alternates, modified.get(path, "")))
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
