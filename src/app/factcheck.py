"""Checking a claim's evidence against the page it came from, on one press.

A pack ships evidence rather than verdicts, which puts the reader in a strange
spot: a claim is a sentence plus a quote plus a URL, and the only way to know
whether the source still says that was to open the link and read it. This
module is that reading, done mechanically.

**It is a re-check, not a review.** The question asked here is narrow and
answerable without judgement: *does the quote this claim rests on still appear
on the page it was taken from?* Nothing about whether the claim is true. That
narrowness is what keeps it inside the automation principle — no human in the
data path, and no LLM either. A model asked "is this claim correct" would
answer confidently and unaccountably; a substring test answers one honest
question and can be wrong only in ways a reader can check themselves.

**Four verdicts, and only one of them is bad news:**

* ``quoted`` — the quote is on the page now.
* ``missing`` — the page was read and the quote is not in it. Not a
  refutation: pages get rewritten, and CMS templates change. It is a *signal*,
  which is why it lands beside the reader's marks (`app/web/state.py`) rather
  than in the engine's store, and changes no ranking at all.
* ``unreadable`` — fetched, but not text this can search (a PDF, a video page
  whose words are in the transcript rather than the HTML). Absence of proof.
* ``unreachable`` — the fetch failed. Says nothing about the claim.

The engine has no authority to retract a claim and this module is not a way to
give it one. It fails open in the strong sense: a ``missing`` verdict is
recorded, shown, and otherwise inert.

**Why the matching is loose about whitespace and case, when `findings.py` is
strict.** They are different questions. Accepting *new* evidence must be
strict, because an agent that reconstructs a quote from memory has to fail
loudly. Re-checking *stored* evidence is comparing text extracted by one
pipeline against text extracted by another one years later — a curly
apostrophe, a non-breaking space or a re-cased heading is an artefact of the
extractor, and calling that "the source no longer says this" would be a lie
told confidently. So both sides are flattened first, and only then compared.
"""

import re
import unicodedata
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urlparse

#: One press by a reader, so the whole check has to finish inside their
#: patience rather than inside a job. A slow source is an `unreachable`, which
#: is the honest answer anyway — the reader cannot read it either.
TIMEOUT = 8
#: Enough for any article; small enough that a wrong URL cannot fill memory.
MAX_BYTES = 4 * 1024 * 1024
#: Named, not disguised as a browser. This is an app re-reading a page it was
#: pointed at, and a site that would rather not be read that way is entitled
#: to say so — an `unreachable` verdict is the correct outcome then.
USER_AGENT = "kriko-factcheck"

QUOTED, MISSING, UNREADABLE, UNREACHABLE = (
    "quoted",
    "missing",
    "unreadable",
    "unreachable",
)
VERDICTS = (QUOTED, MISSING, UNREADABLE, UNREACHABLE)

#: Characters an extractor is free to change without changing the sentence.
_SAME = {
    " ": " ",
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "–": "-",
    "—": "-",
    "−": "-",
    "…": "...",
}


def flatten(text: str) -> str:
    """The comparable form of a piece of text. See the module docstring."""
    text = unicodedata.normalize("NFKC", text)
    for character, plain in _SAME.items():
        text = text.replace(character, plain)
    return re.sub(r"\s+", " ", text).strip().casefold()


class _Text(HTMLParser):
    """HTML to something searchable, with no third-party dependency.

    `app/` is what gets frozen into the sidecar, so a parser here is a stdlib
    parser. It does not have to be a good renderer: the only thing done with
    the output is looking for a sentence in it, and for that, dropping the
    script and style bodies and putting a space between elements is the whole
    requirement.
    """

    _SKIP = {"script", "style", "noscript", "template", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._muted = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._muted += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._muted:
            self._muted -= 1

    def handle_data(self, data):
        if not self._muted:
            self.parts.append(data)

    def text(self) -> str:
        # A space, not nothing: `<p>done</p><p>at 90k</p>` is two sentences,
        # and joining them bare invents the word "doneat".
        return " ".join(self.parts)


def text_of(body: bytes, content_type: str) -> str | None:
    """Searchable text, or None when this is not text at all."""
    kind = content_type.split(";", 1)[0].strip().lower()
    if kind and not (kind.startswith("text/") or kind in {
        "application/xhtml+xml",
        "application/xml",
        "application/json",
    }):
        return None
    charset = "utf-8"
    if "charset=" in content_type:
        charset = content_type.split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
    try:
        decoded = body.decode(charset, errors="replace")
    except LookupError:
        decoded = body.decode("utf-8", errors="replace")
    if kind in {"text/html", "application/xhtml+xml"} or "<html" in decoded[:2000].lower():
        parser = _Text()
        parser.feed(decoded)
        return parser.text()
    return decoded


def fetch(url: str, opener=None) -> tuple[str | None, str]:
    """Read one page. Returns (text, error) — text None means nothing to search.

    `opener` exists so every path through this module is testable with no
    socket, which matters more here than usual: the interesting cases are the
    failures, and a test that needs the network to reach them would be skipped
    on the machine that most needs it.
    """
    if urlparse(url).scheme not in ("http", "https"):
        # A pack is remote data. `file://` in a source row would read the
        # reader's disk on a pack author's say-so.
        return None, f"not an http(s) address: {url}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with (opener or urllib.request.urlopen)(request, timeout=TIMEOUT) as response:
            body = response.read(MAX_BYTES)
            content_type = response.headers.get("Content-Type", "") or ""
    except urllib.error.HTTPError as cause:
        return None, f"the site answered {cause.code}"
    except (urllib.error.URLError, OSError, ValueError) as cause:
        reason = getattr(cause, "reason", cause)
        return None, f"could not read the page: {reason}"
    return text_of(body, content_type), ""


def check_source(quote: str, url: str, opener=None) -> dict:
    """One evidence row against its page."""
    if not quote:
        return {"url": url, "verdict": UNREADABLE, "detail": "the claim carries no quote"}
    text, error = fetch(url, opener=opener)
    if error:
        return {"url": url, "verdict": UNREACHABLE, "detail": error}
    if text is None:
        return {
            "url": url,
            "verdict": UNREADABLE,
            "detail": "the page is not text this can search — open it yourself",
        }
    if flatten(quote) in flatten(text):
        return {"url": url, "verdict": QUOTED, "detail": ""}
    return {
        "url": url,
        "verdict": MISSING,
        "detail": "the page no longer carries this quote — it may have been rewritten",
    }


#: Best first. A claim whose evidence is one confirmed quote and two dead links
#: is a claim whose evidence held up; the reverse reading would make every
#: claim with an old source look refuted.
_ORDER = (QUOTED, MISSING, UNREADABLE, UNREACHABLE)


def check_claim(sources: list[dict], opener=None, limit: int = 3) -> dict:
    """Re-check up to `limit` of a claim's sources, and summarise.

    `limit` because this runs inside a request the reader is waiting on, and
    because the answer stops changing: the first quote that is still on its
    page has already settled the question this asks.
    """
    rows: list[dict] = []
    for source in sources:
        url = (source.get("url") or "").strip()
        if not url:
            continue
        rows.append(check_source(source.get("quote") or "", url, opener=opener))
        if rows[-1]["verdict"] == QUOTED or len(rows) >= max(1, limit):
            break
    if not rows:
        return {
            "verdict": UNREADABLE,
            "detail": "this claim cites no page to re-read",
            "sources": [],
        }
    verdict = min((r["verdict"] for r in rows), key=_ORDER.index)
    return {
        "verdict": verdict,
        "detail": next((r["detail"] for r in rows if r["verdict"] == verdict), ""),
        "sources": rows,
    }
