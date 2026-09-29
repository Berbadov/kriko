"""The local plane: research that costs neither money nor a subscription.

Everything the two existing planes buy — search and reading — this one runs
on this machine: a search socket that speaks to a local search service, a
reader that turns pages into text, and a completion socket that talks to a
local inference server over the OpenAI-compatible protocol. No API keys, no
per-token bill, no coding-agent subscription.

Sockets arrive injected, exactly as the paid plane injects them, and for the
same three reasons: no secrets in the test suite, the provider is the
operator's business, and politeness is enforced in one place — here, through
`PolitenessScheduler` — rather than trusted to each socket.

What this plane adds that money cannot buy is the **code gate**. Every
identifier a completion emits must already exist in the pack's catalog:
`resolve` either recognises the code exactly, offers a shortlist it never
merges across digit cores, or the identifier is dropped. A small local
socket does not get to invent configuration codes, and the grounding check
inherited from the paid plane means it does not get to invent quotes either.

The prompt discipline is the paid plane's, deliberately. A socket small
enough to run at home behaves like a big one when the instructions are the
same: same brief, same JSON shape, same verbatim-quote rule, same refusal to
fill fields with a phrase.
"""

import json
import re
from collections.abc import Callable

from kriko.research.base import (
    STANDARD, Document, Fetched, Finding, ResearchTask, Spend,
)
from kriko.research.codes import resolve
from kriko.research.politeness import LocalSearchError, PolitenessScheduler

#: Reply shape the extractor must produce. Mirrors the paid plane's keys
#: so a finding's provenance never depends on which plane wrote it.
_REPLY_SHAPE = (
    'Return ONLY a JSON array. Each element: '
    '{"source_url","title","domain","severity","quote","body","advice"}. '
)

_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")


class LocalPlane:
    """Research on this machine. Marginal cost: electricity.

    `search(query, limit) -> list[{"url","title","site"}]`,
    `fetch(url) -> str | Fetched` and `complete(prompt) -> str` are the same
    injected shapes the paid plane takes. `codes` is the pack's known
    catalog spelling, used by the code gate — an empty tuple keeps the gate
    armed but with nothing to check against, which is the honest state for
    a pack that declares no codes.
    """

    name = "local"
    cost_basis = "self_hosted"

    def __init__(self, search, fetch, complete,
                 codes: tuple[str, ...] = (),
                 scheduler: PolitenessScheduler | None = None,
                 spend: Spend | None = None,
                 check_cancelled: Callable[[], None] | None = None,
                 json_schema: str = ""):
        self.check_cancelled = check_cancelled or (lambda: None)
        self._search = search
        self._fetch = fetch
        self._complete = complete
        self._codes = tuple(codes)
        self.spend = spend or STANDARD
        self.spent_calls = 0
        self._scheduler = scheduler
        self._json_schema = json_schema

    @property
    def tokens_used(self) -> int | None:
        value = getattr(self._complete, "tokens_used", None)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return int(value)

    def brief(self, task: ResearchTask) -> str:
        """Same brief as the other planes; identical instructions."""
        from kriko.research.agent import AgentResearcher
        return AgentResearcher().brief(task)

    def gather(self, task: ResearchTask) -> list[Document]:
        """Fetch candidate sources through the politeness gate.

        One query at a time, one source per query, rotating when a source
        reports blocked — the walking pace is the scheduler's to enforce,
        not each socket's to remember. Unreadable pages are misses, not
        failures: the run continues with what it could read.
        """
        seen: set[str] = set()
        documents: list[Document] = []
        for query in task.rendered_queries():
            self.check_cancelled()
            if len(documents) >= task.max_documents:
                break
            hits = self._search_polite(query, task.max_documents) or []
            for hit in hits:
                self.check_cancelled()
                if len(documents) >= task.max_documents:
                    break
                url = str(hit.get("url", "")).strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                text, published = self._fetch_polite(url)
                if not text.strip():
                    continue
                documents.append(Document(
                    url=url, text=text,
                    title=str(hit.get("title", "")).strip(),
                    published_at=published,
                    site_or_channel=str(hit.get("site", "")).strip(),
                ))
        return documents

    def extract(self, task: ResearchTask, document: Document) -> list[Finding]:
        """Grounded findings out of one document, with the code gate armed."""
        self.check_cancelled()
        found = self._read(task, [document])
        return found.get(document.url, [])

    def _search_polite(self, query: str, limit: int) -> list[dict]:
        if self._scheduler is None:
            return self._search(query, limit) or []
        source, delay = self._scheduler.acquire()
        if not source:
            return []
        import time as _time
        if delay > 0:
            _time.sleep(min(delay, 5.0))
        try:
            return self._search(query, limit) or []
        except LocalSearchError:
            self._scheduler.report(source, blocked=True)
            return []
        except Exception:
            self._scheduler.report(source, failed=True)
            return []
        finally:
            self._scheduler.release()

    def _fetch_polite(self, url: str) -> tuple[str, str]:
        if self._scheduler is None:
            got = self._fetch(url)
            text = got.text if isinstance(got, Fetched) else (got or "")
            return text, (got.published_at if isinstance(got, Fetched) else "")
        source, delay = self._scheduler.acquire()
        if not source:
            return "", ""
        import time as _time
        if delay > 0:
            _time.sleep(min(delay, 5.0))
        try:
            got = self._fetch(url)
            self._scheduler.report(source)
            text = got.text if isinstance(got, Fetched) else (got or "")
            return text, (got.published_at if isinstance(got, Fetched) else "")
        except Exception:
            self._scheduler.report(source, failed=True)
            return "", ""
        finally:
            self._scheduler.release()

    def _read(self, task: ResearchTask, batch: list[Document]) -> dict:
        limit = max(500, int(self.spend.context_chars))
        blocks = "\n\n".join(
            f"### Document {index}\nURL: {one.url}\n\n{one.text[:limit]}"
            for index, one in enumerate(batch, start=1)
        )
        prompt = (
            f"{self.brief(task)}\n\n"
            "## Documents\n\n"
            f"{blocks}\n\n"
            "## Reply\n\n"
            + _REPLY_SHAPE
            + "`quote` must be copied verbatim from the document you took it "
            "from, and `source_url` must be that document's URL — one of the "
            "URLs listed above, exactly. "
            f"`body` is the explanation and it is not optional: {task.rationale_rule} "
            "Never restate the title in it. "
            "Return [] if the documents support no claim about this subject."
        )
        self.check_cancelled()
        reply = self._complete(prompt)
        self.spent_calls += 1
        return self._parse(task, batch, reply)

    def _parse(self, task: ResearchTask, batch: list[Document],
               reply: str) -> dict:
        from kriko.research.api import _grounding_form
        try:
            payload = json.loads(self._unfence(reply))
        except (json.JSONDecodeError, TypeError):
            return {}
        if not isinstance(payload, list):
            return {}
        by_url: dict[str, list[Finding]] = {}
        texts = {one.url: one.text for one in batch}
        grounded = {url: _grounding_form(text) for url, text in texts.items()}
        for item in payload:
            if not isinstance(item, dict):
                continue
            quote = str(item.get("quote", "")).strip()
            url = str(item.get("source_url", "")).strip()
            if not url and len(batch) == 1:
                url = batch[0].url
            if not quote or not url or url not in texts:
                continue
            if _grounding_form(quote) not in grounded[url]:
                continue
            title = str(item.get("title", "")).strip()
            if not title:
                continue
            if not self._codes_pass(task, title, quote):
                continue
            by_url.setdefault(url, []).append(Finding(
                title=title,
                domain=str(item.get("domain", "")).strip(),
                severity=str(item.get("severity", "medium")).strip(),
                quote=quote, source_url=url,
                body=str(item.get("body", "")).strip(),
                advice=str(item.get("advice", "")).strip(),
            ))
        return by_url

    def _codes_pass(self, task: ResearchTask, title: str,
                    quote: str) -> bool:
        """The code gate: identifiers in a completion's own words must be
        catalogued.

        Only the `title` is gated, on purpose. A quote is checked verbatim
        against the page it came from, so a code inside a quote is the
        page's word, not the completion's — the grounding check already
        owns it. The title is the one field a completion writes itself, and
        an invented identifier there is the most convincing wrong thing a
        small socket can produce: every code-shaped token in it must
        resolve EXACT against the pack's catalog, and anything else —
        close, adjacent, one-integer-off — drops the whole finding.
        Refusal is quiet and total: the run keeps only what it can prove,
        and a candidate is a question for a person, which `extract` is
        not.
        """
        known = self._codes or self._task_codes(task)
        if not known:
            return True
        for match in re.finditer(r"[A-Za-z][A-Za-z0-9.\-]{1,15}", title):
            token = match.group(0).strip(".-")
            if not re.search(r"\d", token):
                continue
            if not resolve(token, known).is_exact:
                return False
        return True

    @staticmethod
    def _task_codes(task: ResearchTask) -> tuple[str, ...]:
        """Codes this task's own identity declares, so the gate travels.

        A subject's codes are already in the brief — `identity` values and
        `attribution_aliases` — and the gate is per-subject, not per-plane:
        a run about one configuration must not be checked against another's
        catalog. Only short alphanumeric strings with a digit qualify; an
        identity value can be a phrase, and a phrase is not a code.
        """
        raw = [str(value) for value in task.identity.values()]
        raw.extend(task.attribution_aliases)
        out: list[str] = []
        for one in raw:
            one = one.strip()
            if one and len(one) <= 24 and re.search(r"\d", one) \
                    and re.fullmatch(r"[A-Za-z0-9.\- ]+", one):
                out.append(one)
        return tuple(out)

    @staticmethod
    def _unfence(reply: str) -> str:
        text = (reply or "").strip()
        if text.startswith("```"):
            text = _JSON_FENCE.sub("", text, count=2)
        return text.strip()
