"""Whether a claim's evidence is worth shipping.

The owner's rule, in one line: AI-written prose is fine, but the *claim* must
come from a source that stands behind it. A recall or safety claim needs an
official source; an owner-report claim needs several independent complaints,
not one. Nothing here judges the writing — only where the words were read.

So this module answers one question per source: which of six tiers is it?

    official    a government, regulator, recall register, standards body or
                testing lab; and a manufacturer's own support/wiki page for a
                claim about *that* manufacturer's product
    press       an established outlet with editorial review or in-house testing
    community   forums, complaint boards, owner communities (a report, not a
                measurement)
    commercial  marketplaces and retailers; a listing is not evidence
    weak        content farms, lead-generation sites, scraped manuals and
                placeholders — content that exists to be found, not read
    unknown     none of the above; absence of a rule, not a verdict

The tier is stored per source in the built pack (`sources.source_tier`), so a
reader — the site, the phone, an agent — can show it without re-deriving it,
and the per-pack summary lands in `packs.credibility_json`.

Three rules, applied to every claim that ships evidence:

    a. a `high` severity claim needs at least one official source. The owner
       asked for this as a failure; measured against the packs that already
       ship, 440 high claims have no official source, so the default policy
       records it and `Policy(strict=True)` turns it into an error.
    b. a claim whose sources are *all* weak or unknown has nothing to check the
       words against. 251 claims ship that way today, so this too is recorded
       by default and enforced under the same switch — failing them without
       that measurement would have rejected 32 of the 33 packs.
    c. a claim supported only by community sources needs at least two distinct
       domains — one thread is an anecdote, several are a pattern. A warning,
       because a single owner report is still a real report, just a thin one.

Enforcement is `Policy`-driven on purpose. `kriko build` runs with the default
policy (record everything, build on) so existing packs keep building; `kriko
pack build --strict-credibility` fails instead. A build never silently drops a
claim: every finding is written into the pack's `credibility_json`.

The domain lists below are a copy of `tools/source_tier.py` in the website
repository (kriko-website). The two cannot import from each other, so a change
here is a change there — keep them in sync by hand.
"""

from __future__ import annotations

import json
import sqlite3
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import urlsplit

TIERS = ("official", "press", "community", "commercial", "weak", "unknown")

#: Best to worst, for a summary line and for a caller that wants the strongest
#: source a claim has. `unknown` sits below `weak`: a known content farm is at
#: least a named site, while an unrecognised domain says only that nobody has
#: classified it yet.
BEST_FIRST = ("official", "press", "community", "commercial", "weak", "unknown")

OFFICIAL_DOMAINS = frozenset({
    # recall registers and consumer safety authorities
    "cpsc.gov", "saferproducts.gov", "recalls.gov", "recalleurope.com",
    "recalls-rappels.canada.ca", "tc.canada.ca", "consumerproductsafety.gov.sg",
    "ccpc.ie", "incibe.es", "esasafe.com", "electricalsafetyfirst.org.uk",
    "dysonrecall.com", "heaterrecall.com", "regmurcia.com", "admin.ch",
    "gov.im", "parliament.uk", "commonslibrary.parliament.uk", "buckleupnc.org",
    # testing, certification and standards bodies
    "intertek.com", "ul.com", "bsigroup.com", "din.de", "iso.org",
    "cefta.int", "ttja.ee",
    # manufacturer domains the brand rule cannot derive from the brand alone
    "mi.com", "xiaomi.com", "prusa3d.com", "koenic-online.com",
    "britax-roemer.de", "siemens-home.bsh-group.com", "playstation.com",
    "anker-mea.com", "gotraxpro.com", "segway.co.nz", "dreametech.zendesk.com",
    "feelcomfee.com", "midea-klima.com", "crealitycloud.com",
    # fire and consumer protection agencies outside the TLD rule
    "fireandemergency.nz", "data.cimple.eu", "ifs-ev.org",
})



#: Whole TLDs that are official wherever they appear. Suffix matching means
#: `static.nhtsa.gov` and `check-recalls.service.gov.uk` need no entry.
OFFICIAL_SUFFIXES = (
    ".gov", ".gov.uk", ".gov.tr", ".gov.au", ".govt.nz", ".gov.sg", ".gov.hk",
    ".gov.tw", ".gov.cn", ".gov.cy", ".go.jp", ".go.kr", ".gob.do", ".gouv.fr",
    ".gc.ca", ".europa.eu", ".parliament.uk",
)

PRESS_DOMAINS = frozenset({
    # testing, reviews, consumer advocacy
    "rtings.com", "notebookcheck.net", "notebookcheck-ru.com", "techpowerup.com",
    "techspot.com", "tomshardware.com", "pcworld.com", "cnet.com", "pcmag.com",
    "techhive.com", "digitaltrends.com", "engadget.com", "theverge.com",
    "arstechnica.com", "gsmarena.com", "phonearena.com", "androidauthority.com",
    "macrumors.com", "9to5google.com", "bgr.com", "wccftech.com", "guru3d.com",
    "tweaktown.com", "hardwareluxx.de", "computerbase.de", "heise.de",
    "igorslab.de", "hdtvtest.co.uk", "soundguys.com", "audiosciencereview.com",
    "whathifi.com", "techradar.com", "lesnumeriques.com", "dpreview.com",
    "consumerreports.org", "which.co.uk", "quechoisir.org",
    "altroconsumo.it", "ocu.org", "vki.at", "konsument.at", "dtest.sk",
    "ktipp.ch", "deco.proteste.pt", "infocons.org", "test.de",
    # newspapers, agencies and tech/business desks
    "bbc.co.uk", "bbc.com", "theguardian.com", "reuters.com", "apnews.com",
    "nytimes.com", "wsj.com", "bloomberg.com", "cnbc.com", "forbes.com",
    "hurriyet.com.tr", "cnnturk.com", "webtekno.com", "shiftdelete.net",
    "technoseyir.com", "chip.de", "winfuture.de", "futurezone.de",
    "itavisen.no", "tek.no", "hardwarezone.com.sg", "tech.hindustantimes.com",
    "digit.in", "ixbt.com", "ithome.com", "mydigit.cn", "finance.sina.com.cn",
    "businesswire.com", "prnewswire.com", "marketscreener.com", "today.com",
    "clickorlando.com", "wsbt.com", "krgv.com", "theargus.co.uk",
    "wiltsglosstandard.co.uk", "thepeterboroughexaminer.com",
    "english.mathrubhumi.com", "tengrinews.kz", "news.hket.com", "paper.hket.com",
    "hoyaragon.es", "eldiariony.com", "aastocks.com", "motormag.co.kr",
    "autodaily.co.kr", "slashgear.com", "extremetech.com", "gamerant.com",
    "nintendolife.com", "pocket-lint.com", "makeuseof.com", "howtogeek.com",
    "hardware.com.br", "clubedohardware.com.br", "tecnoandroid.it",
    "tuttoandroid.net", "connect.de", "giga.de", "bright.nl", "autoextrem.de",
    "firmenauto.de", "motoryzacja.interia.pl", "motofocus.pl", "francuskie.pl",
    "vibilagare.se", "whatcar.com", "autocar.co.uk", "telegraph.co.uk",
    "carscoops.com", "motorreviewer.com", "carnews.nl", "carsandwrenches.com",
    "mbpassion.de", "fahrzeug-karosserie.de", "produktwarnung.eu",
    "ithardware.pl", "fabbaloo.com", "vuldb.com", "mgsm.pl", "yahoo.com",
    "en.gamegpu.com", "rpp.pe", "interaksyon.philstar.com", "wsws.org",
    "publications.aap.org", "accendoreliability.com", "beta.rtbf.be",
    "campusfiresafety.org", "it-daily.net", "medianama.com", "in.mashable.com",
    "lydogbilde.no", "audiowords.net", "moottori.fi", "tinhte.vn", "d1ev.com",
    "360game.360.cn", "weekly.ascii.jp", "s4.biz.itc.cn",
    "jd.big5.enorth.com.cn", "emby.media", "incompliancemag.com",
})



#: Host labels that are a forum by shape, wherever the domain is from.
COMMUNITY_PREFIXES = (
    "forum.", "forums.", "community.", "bbs.", "board.", "club.", "foro.",
)

COMMUNITY_DOMAINS = frozenset({
    "reddit.com", "sikayetvar.com", "trustpilot.com", "donanimhaber.com",
    "technopat.net", "techolay.net", "inceleriz.com", "eksisozluk.com",
    "ifixit.com", "reclameaqui.com.br", "pissedconsumer.com",
    "complaintsboard.com", "reclabox.com", "reklamation24.de",
    "reviews.yandex.ru", "otvet.mail.ru", "zhihu.com", "4pda.to",
    "elotrolado.net", "forocoches.com", "gbatemp.net", "linustechtips.com",
    "xdaforums.com", "avsforum.com", "avforums.com", "mavicpilots.com",
    "phantomhelp.com", "appliancepartspros.com", "whirlpool.net.au",
    "electricunicycle.org", "ebikesforum.com", "teamhack.de", "drucktipps3d.de",
    "electronicwerkstatt.de", "kuechen-forum.de", "roboter-forum.de",
    "repaircafe-forum.org", "universal-blue.discourse.group", "feddit.fr",
    "steamcommunity.com", "facebook.com", "youtube.com", "twitter.com",
    "x.com", "instagram.com", "kosuforum.com", "byggahus.se",
    "home-barista.com", "kaelte-treffpunkt.de", "lesimprimantes3d.fr",
    "anandtech.com", "h30434.www3.hp.com", "forum.dji.com", "forum.dreametech.com",
    "discourse.group", "stackexchange.com", "quora.com", "github.com",
    "post.smzdm.com", "roboter-forum.com", "note.com", "kaffee-welt.net",
    "overclockers.ua", "voz.vn", "erji.znds.com", "webos-forums.ru",
    "tousu.sina.com.cn", "tousu.sina.cn", "althacker.news",
})



#: Marketplaces and retailers, by host label: `m.alza.cz` and `amazon.co.jp`
#: both match without listing each country.
COMMERCIAL_LABELS = frozenset({
    "amazon", "ebay", "alza", "galaxus", "woot", "dns-shop", "pccomponentes",
    "mediamarkt", "saturn", "geizhals", "idealo", "skroutz", "wallapop",
    "3djake",
})

COMMERCIAL_DOMAINS = frozenset({
    "trendyol.com", "hepsiburada.com", "n11.com", "media-amazon.com",
    "digitec.ch", "walmart.com", "bestbuy.com", "bbystatic.com", "fnac.com",
    "bol.com", "mvideo.ru", "220-volt.ru", "technodom.kz", "hotline.ua",
    "catalog.onliner.by", "market.yandex.ru", "backmarket.co.uk", "makro.co.za",
    "thomann.co.uk", "joesge.com", "partselect.com", "appliancesonline.com.au",
    "pbtech.com", "aio.lv", "aetka.de", "e.leclerc", "sater.lv",
    "buywisely.com.au", "spainsellers.com", "hometechsupply.com",
    "heatingandcateringparts.com", "uygunparca.com", "supremephoneparts.com",
    "nickselectronics.com", "hwp.com.tr", "comfy.ua", "sav.darty.com",
    "darty.com", "currys.co.uk", "argos.co.uk", "evetech.co.za", "3djake.com",
    "diy-laptoprepair.com", "phonerepair.co.uk", "repararbaterias.es",
    "jyes.com.tw", "onlineservisim.com", "tradeassistiq.co.uk",
    "support.wholelattelove.com", "prod.danawa.com", "boosted.dk",
    "besbike.co.uk", "electropowerbikes.com", "cofferemont.ru",
    "depanntout.com", "brewive.com", "sdindianaphones.com", "ifone.de",
    "uk.electronic.partners",
})



WEAK_DOMAINS = frozenset({
    # RFC 2606 placeholders: a claim pointing at one cites nothing at all
    "example.com", "example.org", "example.net", "example.invalid",
    # content farms, scraped manual mirrors and lead generation
    "yorumlarnasil.com", "redditrecs.com", "deepwiki.com", "manualslib.com",
    "manualzz.com", "manua.ls", "manualmachine.com", "manuals.plus",
    "manualowl.com", "what-breaks.com", "araclo.com", "autozilla.co.uk",
    "aboutthecars.com", "torquecars.com", "carreliabilityreport.com",
    "problemsbyvin.com", "whocanfixmycar.com", "clickmechanic.com",
    "bumper.co", "smartcarcheck.co.uk", "carcostcheck.co.uk", "lemberglaw.com",
    "farzanlaw.com", "theclarkfirmtexas.com", "vitallaw.com", "margarianlaw.com",
    "americaslemonlawyer.com", "johnsonbecker.com", "aboutlawsuits.com",
    "classactionlawsuithelp.com", "topclassactions.com", "butler.legal",
    "senecarivertrading.com", "syaomaster.vercel.app", "hoverboardsguide.com",
    "laptoprepairworld.com", "easybear-appliancerepair.com", "lmlrepair.com",
    "pcmacgicians.co.uk", "hometechsupply.com",
    # paid Q&A sites and error-code aggregators: answers without a source
    "justanswer.com", "aretec.nl", "servisfer.com", "smartfehler.de",
    "code-erreur-pompe-a-chaleur.fr", "kullanimkilavuzu.com.tr",
    "justanswer.de", "justanswer.co.uk", "manualslib.de", "forms.office.com",
    "schmidtandclark.com", "google.com.tw", "google.co.in", "google.com.do",
    "google.co.zw", "google.com.sa", "google.it", "google.com.pe",
})



#: Second-level publics (`example.co.uk`) that a registrable label must keep.
_SECOND_LEVEL = frozenset({
    "co.uk", "org.uk", "ac.uk", "com.tr", "com.au", "co.jp", "co.kr", "com.br",
    "co.nz", "co.za", "com.mx", "com.sg", "com.hk", "com.tw", "co.in", "com.cn",
    "com.ar", "com.ua", "co.il", "com.my", "com.ph", "com.vn", "com.eg",
    "com.sa", "com.pe", "com.co", "com.do", "co.id", "com.pk", "com.ng",
    "com.kw", "com.qa", "com.bh", "com.om", "com.jo", "com.lb", "co.at",
    "gov.uk", "gov.tr", "gob.do", "gouv.fr", "gc.ca", "go.jp", "go.kr",
})


def domain_of(url: str) -> str:
    """The host a URL points at, lower case, without `www.` or a port."""
    host = urlsplit(str(url or "").strip()).netloc.lower()
    host = host.rsplit("@", 1)[-1].split(":", 1)[0]
    return host.removeprefix("www.")


def _labels(domain: str) -> list[str]:
    return [part for part in domain.split(".") if part]


def _registrable(domain: str) -> str:
    """The last two labels, or three where the middle one is a public suffix."""
    labels = _labels(domain)
    if len(labels) >= 3 and ".".join(labels[-2:]) in _SECOND_LEVEL:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _fold(text: str) -> str:
    """Letters and digits only, with accents folded away (`Römer` == `Roemer`)."""
    plain = unicodedata.normalize("NFKD", str(text or ""))
    plain = plain.encode("ascii", "ignore").decode("ascii").casefold()
    return "".join(ch for ch in plain if ch.isalnum())


def _matches(domain: str, known) -> bool:
    """Whether `domain` is in `known` or is a subdomain of a name in it."""
    return any(domain == name or domain.endswith("." + name) for name in known)


#: The words a manufacturer appends to its own name on its own domains:
#: `joiebaby.com`, `dysonrecall.com`, `prusa3d.com` (the digit tail is folded in
#: with the name). Anything else after the brand is somebody else — an importer,
#: a reseller, a fan wiki — and stays out of `official`.
_BRAND_TAILS = frozenset({
    "baby", "global", "online", "official", "care", "support", "service",
    "home", "store", "shop", "recall", "electronics", "appliances", "3d",
})


def _is_brand_own(domain: str, brand: str) -> bool:
    """Whether `domain` is the manufacturer of `brand` speaking for itself.

    A manufacturer's support page is official *for its own product*: the notice
    a maker signs about its own product is the notice. The match is on the
    registrable label, so `support.anker.com` counts and `anker-mea.com` does
    not: a looser rule would promote the importer, the reseller and the fan
    wiki along with the maker. A brand identity may name two makers
    (`arcelik-beko`), so a single folded token of the brand also counts.
    """
    slug = _fold(brand)
    if len(slug) < 2:
        return False
    label = _fold(_registrable(domain).split(".")[0])
    if label == slug:
        return True
    if label in {_fold(token) for token in str(brand).replace("-", " ").split()}:
        return True
    return label.startswith(slug) and label[len(slug):] in _BRAND_TAILS


def tier(url: str, brand: str = "") -> str:
    """The tier of one source URL: official, press, community, commercial, weak or unknown.

    `brand` is the subject's brand, used only for the manufacturer case; pass
    it whenever the claim is about a named maker's product.
    """
    domain = domain_of(url)
    if not domain:
        return "unknown"
    if _matches(domain, WEAK_DOMAINS):
        return "weak"
    if _matches(domain, COMMUNITY_DOMAINS) or domain.startswith(COMMUNITY_PREFIXES):
        return "community"
    if _matches(domain, OFFICIAL_DOMAINS):
        return "official"
    if any(domain == s.lstrip(".") or domain.endswith(s) for s in OFFICIAL_SUFFIXES):
        return "official"
    if _is_brand_own(domain, brand):
        return "official"
    if _matches(domain, PRESS_DOMAINS):
        return "press"
    if _matches(domain, COMMERCIAL_DOMAINS):
        return "commercial"
    if set(_labels(domain)) & COMMERCIAL_LABELS:
        return "commercial"
    return "unknown"


@dataclass(frozen=True)
class Policy:
    """Which findings stop a build, and which are recorded.

    `strict` is the owner's decision point. Off (the default), every finding is
    written into the pack's `credibility_json` and printed, and the build
    continues; on, a high severity claim without an official source and a claim
    with no credible source both stop it.

    It ships off because the catalogs already in the repo were measured against
    these rules: 440 high-severity claims have no official source and 251 claims
    have nothing but weak or unknown ones. Turning it on rejects 32 of the 33
    packs that ship today. That is a decision about the catalog, not about the
    builder — see the task report — so the builder records and the owner decides.
    """

    strict: bool = False
    community_min_domains: int = 2


@dataclass(frozen=True)
class Issue:
    rule: str
    claim: str
    detail: str
    error: bool

    def line(self) -> str:
        mark = "error" if self.error else "warning"
        return f"{mark}: [{self.rule}] {self.claim}: {self.detail}"


@dataclass
class Report:
    pack: str
    claims: int
    tiers: Counter = field(default_factory=Counter)
    issues: list[Issue] = field(default_factory=list)

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.error]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if not i.error]

    def as_dict(self) -> dict:
        return {
            "claims": self.claims,
            "sources": {t: self.tiers[t] for t in TIERS if self.tiers[t]},
            "errors": [i.line() for i in self.errors],
            "warnings": [i.line() for i in self.warnings],
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True)

    def summary(self) -> str:
        counts = ", ".join(f"{t} {self.tiers[t]}" for t in TIERS if self.tiers[t])
        return (
            f"{self.pack}: {self.claims} claims, sources: {counts or 'none'}; "
            f"{len(self.errors)} error(s), {len(self.warnings)} warning(s)"
        )


def judge(pack: str, claims: list[dict], policy: Policy = Policy(),
          identity_keys: dict[str, list[str]] | None = None) -> Report:
    """Apply the three rules to claims shaped like `data/claims.yaml`.

    Each claim is `{severity, text, subject: {identity: {<first key>}},
    evidence: [{url}]}`. The subject's brand is its first identity attribute,
    per the pack's own `[identity]` declaration — the same rule the builder
    uses, so a pack that names the maker `make` is not a special case here.

    A claim with no evidence at all is skipped: it is a proposal, not a
    finding, and the site and the phone already leave it out.
    """
    report = Report(pack=pack, claims=len(claims))
    first_key = {kind: keys[0] for kind, keys in (identity_keys or {}).items() if keys}
    for number, claim in enumerate(claims, 1):
        sources = claim.get("evidence") or []
        if not sources:
            continue
        subject = claim.get("subject") or {}
        identity = subject.get("identity") or {}
        key = first_key.get(str(subject.get("kind")), "brand")
        brand = str(identity.get(key) or "")
        texts: dict[str, dict] = claim.get("text") or {}
        title = ((texts.get("en") or next(iter(texts.values()), {})) or {}).get("title") or ""
        label = f"claim {number}" + (f" {title!r}" if title else "")
        severity = str(claim.get("severity") or "medium")
        tiers = []
        domains = set()
        for source in sources:
            url = str(source.get("url") or source.get("source_url") or "")
            found = tier(url, brand)
            tiers.append(found)
            report.tiers[found] += 1
            if domain_of(url):
                domains.add(domain_of(url))
        _apply_rules(report, label, severity, tiers, domains, policy)
    return report


def _apply_rules(report: Report, label: str, severity: str, tiers: list[str],
                 domains: set[str], policy: Policy) -> None:
    if severity == "high" and "official" not in tiers:
        strongest = min(tiers, key=BEST_FIRST.index)
        report.issues.append(Issue(
            rule="high-without-official",
            claim=label,
            detail=(f"severity is high but no source is official "
                    f"(best is {strongest}, {len(domains)} domain(s))"),
            error=policy.strict,
        ))
    if all(found in ("unknown", "weak") for found in tiers):
        listed = ", ".join(sorted(domains)) or "no readable domain"
        report.issues.append(Issue(
            rule="no-credible-source",
            claim=label,
            detail=f"every source is weak or unknown ({listed}) — nothing to check the words against",
            error=policy.strict,
        ))
    elif all(found == "community" for found in tiers) and len(domains) < policy.community_min_domains:
        listed = ", ".join(sorted(domains)) or "no readable domain"
        report.issues.append(Issue(
            rule="single-community-domain",
            claim=label,
            detail=(f"owner reports come from one domain only ({listed}); "
                    f"{policy.community_min_domains} independent complaints form a pattern"),
            error=False,
        ))


class CredibilityError(ValueError):
    """A pack whose evidence breaks a rule that stops the build."""

    def __init__(self, report: Report):
        self.report = report
        super().__init__(
            f"{report.pack}: {len(report.errors)} credibility error(s); first: "
            + report.errors[0].line()
        )


def enforce(report: Report) -> Report:
    """Raise `CredibilityError` if the report holds any error."""
    if report.errors:
        raise CredibilityError(report)
    return report


#: A pack's own trust vocabulary, mapped onto the six tiers this module uses.
#: Anything else the pack invented (and did not weight) falls back to the
#: global lists, which is why this is a lookup and not a passthrough.
PACK_TIERS = {
    "authoritative": "official",
    "manufacturer": "official",
    "specialist": "press",
    "enthusiast": "community",
    "forum_ugc": "community",
    "seo_blog": "weak",
}


def _pack_tiers(conn) -> dict[str, str]:
    """The pack's own `trust/source_tiers.yaml`, as the builder wrote it."""
    try:
        rows = conn.execute("SELECT domain_pattern, tier FROM source_tiers").fetchall()
    except sqlite3.OperationalError:  # a pack built before the table existed
        return {}
    return {row[0]: row[1] for row in rows}


def _resolve(url: str, brand: str, declared: dict[str, str]) -> str:
    """The tier of a source, with the pack's own registry filling the gaps.

    The global lists win wherever they have an opinion: a curated press list
    beats a pack author's enthusiasm. Where they do not — a repairer, a local
    forum, an outlet nobody central has classified — the pack's registry is the
    only knowledge in the room, and it is used rather than discarded.
    """
    found = tier(url, brand)
    if found != "unknown" or not declared:
        return found
    from kriko.lookup.rank import tier_of

    return PACK_TIERS.get(tier_of(domain_of(url), declared), "unknown")


def audit_built(conn, identity_keys: dict, pack: str = "",
                policy: Policy = Policy()) -> Report:
    """Audit a built pack in place, writing `sources.source_tier` as it goes.

    Reading the built rows rather than the authoring files is what makes this
    one implementation for every pack: a pack with its own `build.py` writes
    claims the generic builder never sees, and it must be checked the same way.
    The brand a claim is about comes from the subject's first identity
    attribute, which every pack declares in `pack.toml`.
    """
    first_key = {kind: keys[0] for kind, keys in identity_keys.items() if keys}
    kind_of = dict(conn.execute("SELECT subject_id, kind FROM subjects"))
    brands = {}
    for subject_id, key, value in conn.execute(
            "SELECT subject_id, key, value_text FROM attributes WHERE is_identity = 1"):
        if key == first_key.get(kind_of.get(subject_id, "")):
            brands[subject_id] = value or ""

    report = Report(pack=pack, claims=0)
    by_claim: dict[str, dict] = {}
    for claim_id, subject_id, severity in conn.execute(
            "SELECT claim_id, subject_id, severity FROM claims"):
        report.claims += 1
        by_claim[claim_id] = {"severity": severity, "brand": brands.get(subject_id, ""),
                              "title": "", "sources": []}
    for claim_id, title in conn.execute(
            "SELECT claim_id, title FROM claim_text WHERE lang = 'en'"):
        if claim_id in by_claim:
            by_claim[claim_id]["title"] = title
    for claim_id, source_id, url in conn.execute(
            "SELECT e.claim_id, s.source_id, s.url FROM evidence e JOIN sources s USING (source_id)"):
        claim = by_claim.get(claim_id)
        if claim is not None:
            claim["sources"].append((source_id, url))

    declared = _pack_tiers(conn)
    for number, claim in enumerate(by_claim.values(), 1):
        if not claim["sources"]:
            continue
        label = f"claim {number}" + (f" {claim['title']!r}" if claim["title"] else "")
        tiers, domains = [], set()
        for source_id, url in claim["sources"]:
            found = _resolve(url, claim["brand"], declared)
            tiers.append(found)
            report.tiers[found] += 1
            conn.execute("UPDATE sources SET source_tier = ? WHERE source_id = ?",
                         (found, source_id))
            if domain_of(url):
                domains.add(domain_of(url))
        _apply_rules(report, label, claim["severity"], tiers, domains, policy)
    return report
