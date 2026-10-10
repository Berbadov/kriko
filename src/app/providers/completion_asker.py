"""A direct hosted completion for supplied-evidence benchmark cases."""

from app import modelcatalogue


class CompletionAsker:
    cost_basis = "per_token"
    search_provider = "supplied-corpus"

    def __init__(self, complete, *, budget_usd: float = 0, max_tokens: int = 1024):
        self.complete = complete
        self.budget_usd = budget_usd
        self.max_tokens = max_tokens
        self.model = str(getattr(complete, "model", ""))

    def ask(self, prompt: str) -> str:
        if self.budget_usd:
            # A conservative preflight, never shown as measured usage. One
            # UTF-8 byte per input token overestimates this bounded prompt.
            ceiling = modelcatalogue.price(self.model, len(prompt.encode("utf-8")) + 256,
                                           self.max_tokens)
            if ceiling is None:
                raise ValueError("cannot enforce a dollar ceiling without model prices; "
                                 "configure prices or explicitly use an uncapped budget")
            if ceiling > self.budget_usd:
                raise ValueError("conservative completion cost exceeds the case budget")
        reply = self.complete(prompt)
        if not reply.strip():
            raise RuntimeError("provider returned no completion; inspect provider logs")
        return reply

    @property
    def tokens_used(self):
        return getattr(self.complete, "tokens_used", None)

    @property
    def usage_complete(self):
        return getattr(self.complete, "usage_complete", self.tokens_used is not None)

    @property
    def last_finish_reason(self):
        return getattr(self.complete, "last_finish_reason", "")

    @property
    def tokens_in(self):
        return getattr(self.complete, "tokens_in", None)

    @property
    def tokens_out(self):
        return getattr(self.complete, "tokens_out", None)

    @property
    def spent(self):
        if not self.usage_complete or self.tokens_in is None or self.tokens_out is None:
            return None
        return modelcatalogue.price(self.model, self.tokens_in, self.tokens_out)
