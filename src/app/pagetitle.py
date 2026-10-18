"""A page's title, reduced to the name of the product it is about.

A listing's `<title>` is written for a search results page: the product, then
the words a shop adds to rank for it ("Prices, Specs and Reviews"), then the
shop. Searched for whole, that title finds nothing about the product. It finds
the shop, and pages that match the shop's own words: one reader's phone listing
came back with chemistry lessons, because "Features, Reviews" and a Turkish shop
name were most of the query.

So the name is what is left once the site and the page-type words are taken off.
Both lists are about *pages*, never about products: the host's own name, and a
small closed vocabulary of the words a shop adds in each language it is read in.
No product, brand or category appears in either.

Pure functions: no model, no network. A title with nothing to take off comes
back as it was, and a title that is nothing *but* those words comes back as it
was too, so this can only make a name shorter, never empty.
"""

import re

from app.providers.local_identity import clean_product_name, fold

#: Separators a title puts between its parts. A dash counts only with spaces
#: around it, because "A54-5G" and "Wi-Fi" are part of a name.
_SPLIT = re.compile(r"\s*[|•·»]\s*|\s+[-–—:]\s+")

#: What a shop adds to a product's name so a search engine ranks the page, and
#: the little words that join them. Folded (no case, no accents, dotless i).
#: Closed and about pages, not products; one list for every language, since a
#: word that is a page-type word in one is rarely a product word in another.
PAGE_WORDS = frozenset(fold(word) for word in (
    # English
    "price", "prices", "specs", "spec", "specifications", "review", "reviews",
    "buy", "online", "compare", "comparison", "deals", "deal", "cheap", "cheapest",
    "features", "and", "offers", "offer",
    # Turkish
    "fiyat", "fiyati", "fiyatı", "fiyatlari", "fiyatları", "özellikleri",
    "özellikler", "yorumları", "yorumlar", "yorum", "incele", "satın", "al",
    "ucuz", "ucuzu", "en", "ve", "karşılaştır", "fiyatlarını",
    # German
    "preis", "preise", "kaufen", "test", "testbericht", "bewertungen",
    "vergleich", "günstig", "und", "technische", "daten", "angebote",
    # French
    "prix", "avis", "acheter", "comparer", "caractéristiques", "fiche",
    "technique", "et", "offres",
    # Spanish
    "precio", "precios", "opiniones", "comprar", "características", "comparar",
    "y", "ofertas",
))

_WORD = re.compile(r"[^\W_]+(?:[.'’][^\W_]+)*", re.UNICODE)
_COMPOUND_SUFFIXES = {"co", "com", "org", "net", "gov", "edu", "ac"}


def _words(text: str) -> list[str]:
    return [fold(word) for word in _WORD.findall(text)]


def _site_label(url: str) -> str:
    """The shop's own name as its address spells it: `akakce` for `www.akakce.com`."""
    from app.sites import host_of

    parts = host_of(url).split(".")
    if len(parts) < 2:
        return ""
    label = parts[-3] if len(parts) >= 3 and parts[-2] in _COMPOUND_SUFFIXES else parts[-2]
    return fold(label) if len(label) >= 3 else ""


def product_name(title: str, url: str = "") -> str:
    """The product a page title names, without its shop or its page-type words."""
    original = " ".join(str(title or "").split())
    if not original:
        return ""
    label = _site_label(url)
    kept: list[str] = []
    for part in (one.strip() for one in _SPLIT.split(original)):
        if not part:
            continue
        words = _words(part)
        if label and label in "".join(words):
            continue
        if words and all(word in PAGE_WORDS for word in words):
            continue
        kept.append(part)
    if not kept:
        return clean_product_name(original)
    name = kept[0].split()
    # Trailing and leading page-type words, but never down to a single word:
    # "Test" alone, or "Best Buy", is a name and not decoration.
    while len(name) > 2 and _words(name[-1]) and all(w in PAGE_WORDS for w in _words(name[-1])):
        name.pop()
    while len(name) > 2 and _words(name[0]) and all(w in PAGE_WORDS for w in _words(name[0])):
        name.pop(0)
    return clean_product_name(" ".join(name).rstrip(",;"))
