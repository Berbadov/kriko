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

from kriko.research.base import Document, Finding, ResearchTask


class BudgetExceeded(RuntimeError):
    """Raised the moment a task would spend past its ceiling."""


class ApiResearcher:
    """Research by spending money. Cost is per token, and it is capped."""

    name = "api"
    cost_basis = "per_token"

    def __init__(self, search, fetch, complete, price_per_call: float = 0.0):
        """
        search(query, limit)  -> list of {"url", "title", "site"}
        fetch(url)            -> plain text, or "" when it cannot be read
        complete(prompt)      -> the model's reply as a string
        """
        self._search = search
        self._fetch = fetch
        self._complete = complete
        self._price = price_per_call
        self.spent = 0.0

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
        return documents

    def extract(self, task: ResearchTask, document: Document) -> list[Finding]:
        self._charge(task)
        prompt = (
            f"{self.brief(task)}\n\n"
            "## Document\n\n"
            f"URL: {document.url}\n\n{document.text[:12000]}\n\n"
            "## Reply\n\n"
            "Return ONLY a JSON array. Each element: "
            '{"title","domain","severity","quote","body","advice"}. '
            "`quote` must be copied verbatim from the document above. "
            "Return [] if the document supports no claim about this subject."
        )
        try:
            payload = json.loads(self._complete(prompt))
        except (json.JSONDecodeError, TypeError):
            return []
        if not isinstance(payload, list):
            return []

        findings = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            quote = str(item.get("quote", "")).strip()
            # Grounding, enforced rather than requested: a quote that is not in
            # the document is a hallucination, and the whole value of the
            # evidence chain is that this cannot happen quietly.
            if not quote or quote not in document.text:
                continue
            findings.append(Finding(
                title=str(item.get("title", "")).strip(),
                domain=str(item.get("domain", "")).strip(),
                severity=str(item.get("severity", "medium")).strip(),
                quote=quote,
                source_url=document.url,
                body=str(item.get("body", "")).strip(),
                advice=str(item.get("advice", "")).strip(),
            ))
        return [f for f in findings if f.title]
