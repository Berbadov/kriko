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

from kriko.research.base import STANDARD, Document, Finding, ResearchTask, Spend


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
                text = self._fetch(url) or ""
                if not text.strip():
                    continue        # unreadable is not a failure, just a miss
                documents.append(Document(
                    url=url, text=text, title=hit.get("title", ""),
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
        prompt = (
            f"{self.brief(task)}\n\n"
            "## Documents\n\n"
            f"{blocks}\n\n"
            "## Reply\n\n"
            "Return ONLY a JSON array. Each element: "
            '{"source_url","title","domain","severity","quote","body","advice"}. '
            "`quote` must be copied verbatim from the document you took it "
            "from, and `source_url` must be that document's URL. "
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
        for item in payload:
            if not isinstance(item, dict):
                continue
            quote = str(item.get("quote", "")).strip()
            url = str(item.get("source_url", "")).strip() or batch[0].url
            # Grounding, enforced rather than requested: a quote that is not in
            # the document is a hallucination, and the whole value of the
            # evidence chain is that this cannot happen quietly. Under a batch
            # this also catches the *attribution* slip — a real quote filed
            # against the wrong document — by checking it against the text of
            # the url the model named, not against whichever page is handy.
            if not quote or quote not in texts.get(url, ""):
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
