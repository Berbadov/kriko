"""The paid plane: Kriko searches and reads for itself.

For people with an Exa or Tavily key and an LLM key rather than a coding-agent
subscription, and for anything that has to run unattended on a schedule.

Search and completion arrive as injected callables rather than hard-wired SDK
calls. Three reasons, in order of how much they matter:

  1. Nobody should need an API key to run the test suite. The whole suite runs
     today with no secrets in the environment and that must not change.
  2. Which provider a person uses is their business, and Exa, Tavily and a
     dozen others all reduce to "text in, results out".
  3. The budget has to be enforced *here*, in one place, rather than trusted to
     each provider adapter.

The budget is a hard stop, not a warning. An unattended pipeline that overshoots
is how a hobby project produces a bill someone remembers.
"""

import json
import re
import unicodedata

from kriko.research.base import (
    STANDARD,
    Document,
    Fetched,
    Finding,
    ResearchTask,
    Spend,
)

#: Characters an extractor or a model is free to swap without changing the
#: sentence. The same rule `app/factcheck.py` applies to a stored quote years
#: later, applied here to a quote seconds after it was produced: a curly
#: apostrophe or a collapsed run of whitespace is not evidence the quote was
#: invented, and rejecting it on that basis would teach nobody anything except
#: to distrust the gate.
_SAME_CHARS = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "−": "-", "…": "...",
}


def _grounding_form(text: str) -> str:
    """The comparable form of a quote or a document, for the grounding check.

    Deliberately loose about whitespace and case and strict about everything
    else — a model that reconstructs a sentence from memory still has to fail,
    and the two things this folds away are cosmetic in every language this
    runs against. Case-folding does not make a fabricated quote harder to
    catch: truth does not live in capitalisation.
    """
    text = unicodedata.normalize("NFKC", text or "")
    for needle, plain in _SAME_CHARS.items():
        text = text.replace(needle, plain)
    return re.sub(r"\s+", " ", text).strip().casefold()


class BudgetExceeded(RuntimeError):
    """Raised the moment a task would spend past its ceiling."""


class ApiResearcher:
    """Research by spending money. Cost is per token, and it is capped."""

    name = "api"
    cost_basis = "per_token"

    def __init__(
        self,
        search,
        fetch,
        complete,
        price_per_call: float = 0.0,
        spend: Spend | None = None,
    ):
        """
        search(query, limit)  -> list of {"url", "title", "site"}
        fetch(url)            -> plain text, or "" when it cannot be read
        complete(prompt)      -> the model's reply as a string
        spend                 -> how much text per call, and how many documents
                                 per call (B123). `STANDARD` when nobody says,
                                 which is exactly the behaviour that existed
                                 before protocols did.
        """
        self._search = search
        self._fetch = fetch
        self._complete = complete
        self._price = price_per_call
        self.spend = spend or STANDARD
        self.spent = 0.0
        #: Findings by url, filled by the batched call and drained per
        #: document. Empty under `batch_size = 1`, which reads every document
        #: in its own call and needs no cache.
        self._batched: dict[str, list[Finding]] = {}
        #: What `gather` kept, so `extract` can assemble a batch out of the
        #: documents nobody has read yet.
        self._documents: list[Document] = []

    @property
    def tokens_used(self) -> int | None:
        """What the completion socket says it spent, or None when it cannot say.

        Read off the injected callable rather than counted here. `complete` is
        "prompt in, text out" by design (see the module docstring), and the
        token count lives in the part of the reply that contract throws away —
        so the only honest place to keep the total is the adapter that saw the
        envelope. A socket that counts exposes a `tokens_used` total; one that
        does not leaves this None, and the provenance row then records "nobody
        counted" rather than a measured zero.

        Not folded into `spent`: dollars and tokens are two different
        measurements, and a plane priced per call can know one without the
        other.
        """
        value = getattr(self._complete, "tokens_used", None)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return int(value)

    def _charge(self, task: ResearchTask) -> None:
        self.spent += self._price
        if task.budget_usd and self.spent > task.budget_usd:
            raise BudgetExceeded(
                f"{task.subject_label}: spent ${self.spent:.4f} of "
                f"${task.budget_usd:.4f} — stopping")

    def brief(self, task: ResearchTask) -> str:
        """Same brief as the agent plane; here it becomes the prompt."""
        from kriko.research.agent import AgentResearcher
        return AgentResearcher().brief(task)

    def gather(self, task: ResearchTask) -> list[Document]:
        seen: set[str] = set()
        documents: list[Document] = []
        self._batched = {}

        for query in task.rendered_queries():
            if len(documents) >= task.max_documents:
                break
            self._charge(task)
            for hit in self._search(query, task.max_documents) or []:
                url = hit.get("url", "")
                if not url or url in seen:
                    continue
                seen.add(url)
                got = self._fetch(url)
                text = got.text if isinstance(got, Fetched) else (got or "")
                published = got.published_at if isinstance(got, Fetched) else ""
                if not text.strip():
                    continue        # unreadable is not a failure, just a miss
                documents.append(Document(
                    url=url, text=text, title=hit.get("title", ""),
                    published_at=published,
                    site_or_channel=hit.get("site", "")))
                if len(documents) >= task.max_documents:
                    break
        # Remembered so `extract` can batch the ones that have not been read
        # yet. The caller hands documents back one at a time, which is the
        # right interface and the reason a batch has to be assembled here.
        self._documents = list(documents)
        return documents

    def extract(self, task: ResearchTask, document: Document) -> list[Finding]:
        """The findings this document supports, under the current protocol.

        **Batching happens here rather than in the caller**, and that is a
        deliberate constraint: `Researcher.extract` is per-document, which is
        the right interface — it is what lets the caller report progress per
        source and attribute every finding to the page it came from. So a
        protocol with `batch_size > 1` reads the *next* few documents in one
        call and caches the rest by url, exactly as the harness plane already
        caches what one CLI run reported. The engine's shape does not change;
        what changes is how many times money is spent to fill it.
        """
        if document.url in self._batched:
            return self._batched.pop(document.url)
        batch = self._take(task, document)
        found = self._read(task, batch)
        for one in batch:
            self._batched[one.url] = found.get(one.url, [])
        return self._batched.pop(document.url, [])

    def repair(self, task: ResearchTask, findings: list[dict],
               verdicts: dict) -> list[dict]:
        """Ask once more for the fields that got these findings refused.

        The failing items only, and only what was wrong with each. Everything
        else about a finding — its quote, its source, its severity — already
        passed and is passed straight back in, because re-deriving it would
        risk a *different* claim coming back under the same title, and the
        quote has already been proved against a document this call no longer
        carries.

        It exists because a refusal like "rationale is 0 chars" is not a
        judgement about the finding. It is a field left empty, on work the
        reader described as genuinely good, and the only reason it could not
        be fixed was that nobody ever asked a second time.
        """
        asks = []
        for one in findings:
            why = verdicts.get(one.get("title", ""), {})
            asks.append({
                "title": one.get("title", ""),
                "what_is_wrong": why.get("reason", ""),
                "quote": one.get("quote", ""),
            })
        prompt = (
            "Some findings you wrote were refused for one fixable field each. "
            "Fix only that field. Do not change the title, the quote, or which "
            "source it came from, and do not invent a new claim.\n\n"
            f"The explanation field (`body`) must be {task.rationale_rule}\n\n"
            "## Refused\n\n"
            + "\n".join(
                f"{index}. {one['title']}\n   refused because: "
                f"{one['what_is_wrong']}\n   its quote: {one['quote'][:400]}"
                for index, one in enumerate(asks, start=1)
            )
            + "\n\n## Reply\n\nReturn ONLY a JSON array, one element per "
              'refused finding above, each {"title","body"}. `title` must be '
              "copied back exactly so each rewrite can be matched to what it "
              "fixes."
        )
        self._charge(task)
        try:
            payload = json.loads(self._complete(prompt))
        except (json.JSONDecodeError, TypeError):
            return []
        if not isinstance(payload, list):
            return []

        rewritten = {
            str(item.get("title", "")).strip(): str(item.get("body", "")).strip()
            for item in payload
            if isinstance(item, dict)
        }
        out = []
        for one in findings:
            body = rewritten.get(str(one.get("title", "")).strip(), "")
            if body:
                out.append({**one, "body": body, "rationale": body})
        return out

    def _take(self, task: ResearchTask, first: Document) -> list[Document]:
        """`first`, plus however many more the protocol says fit in one call.

        The rest of the run's documents are not handed to this method, so the
        batch is built from what `gather` kept — which is why `_documents` is
        remembered there rather than rediscovered here.
        """
        size = max(1, int(self.spend.batch_size))
        if size == 1:
            return [first]
        rest = [
            one
            for one in self._documents
            if one.url != first.url and one.url not in self._batched
        ]
        return [first, *rest[: size - 1]]

    def _read(self, task: ResearchTask, batch: list[Document]) -> dict:
        """One completion for one batch. Returns findings by url."""
        self._charge(task)
        limit = max(500, int(self.spend.context_chars))
        blocks = "\n\n".join(
            f"### Document {index}\nURL: {one.url}\n\n{one.text[:limit]}"
            for index, one in enumerate(batch, start=1)
        )
        preamble = self.spend.preamble_text
        prompt = (
            (f"{preamble}\n\n" if preamble else "")
            + f"{self.brief(task)}\n\n"
            "## Documents\n\n"
            f"{blocks}\n\n"
            "## Reply\n\n"
            "Return ONLY a JSON array. Each element: "
            '{"source_url","title","domain","severity","quote","body","advice"}. '
            "`quote` must be copied verbatim from the document you took it "
            "from, and `source_url` must be that document's URL — one of the "
            "URLs listed above, exactly. "
            # The field the whole run gets refused for if it is left thin, and
            # it was described here only by its name. A model asked for
            # `{"body"}` in a list of seven keys writes a phrase; the gate
            # wants two sentences, and the difference was the entire yield of
            # some runs.
            f"`body` is the explanation and it is not optional: {task.rationale_rule}"
            " Never restate the title in it. "
            "Return [] if the documents support no claim about this subject."
        )
        try:
            payload = json.loads(self._complete(prompt))
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
                # No ambiguity: there is exactly one document this could be,
                # and requiring the model to name it anyway would reject real
                # findings for no safety gained. This is the *only* case a
                # missing url may be defaulted — see the batch case below.
                url = batch[0].url
            # Grounding, enforced rather than requested: a quote that is not in
            # the named document is a hallucination, and the whole value of the
            # evidence chain is that this cannot happen quietly.
            #
            # Three things are checked, not one: under a batch of more than one
            # document, `url` must be non-empty (a finding with no source used
            # to fall back to the *first* document regardless of batch size,
            # which let a fabricated, source-less quote through whenever it
            # happened to also appear on that unrelated page); `url` must be
            # one this batch actually offered (a model citing a page it was
            # never shown resolves to no text at all, never to "the nearest
            # one"); and the quote must appear in *that* page's text — not
            # merely somewhere in the batch — which is what catches a real
            # quote filed against the wrong document. Comparison is via
            # `_grounding_form`, loose about whitespace/case/curly punctuation
            # and strict about everything else, because a model that
            # reconstructs a sentence from memory still has to fail this.
            if not quote or not url or url not in texts:
                continue
            if _grounding_form(quote) not in grounded[url]:
                continue
            title = str(item.get("title", "")).strip()
            if not title:
                continue
            by_url.setdefault(url, []).append(Finding(
                title=title,
                domain=str(item.get("domain", "")).strip(),
                severity=str(item.get("severity", "medium")).strip(),
                quote=quote,
                source_url=url,
                body=str(item.get("body", "")).strip(),
                advice=str(item.get("advice", "")).strip(),
            ))
        return by_url
