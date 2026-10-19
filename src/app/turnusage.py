"""Account for all requests in one conversational turn, including metadata."""

from dataclasses import dataclass

from kriko.research import BudgetExceeded


@dataclass
class TurnUsage:
    budget: float = 0.5
    measured_usd: float = 0.0
    measured_tokens: int = 0
    priced: int = 0
    tokenized: int = 0
    calls: int = 0

    def parameters(self, params: dict) -> dict:
        remaining = self.budget - self.measured_usd
        if remaining <= 0:
            raise BudgetExceeded("The conversation turn reached its spending limit; no further request was sent.")
        return {**params, "budget_usd": remaining}

    def record(self, usage: dict) -> None:
        self.calls += 1
        usd, tokens = usage.get("usd"), usage.get("tokens")
        if isinstance(usd, (int, float)) and usd >= 0:
            self.measured_usd += usd
            self.priced += 1
        if isinstance(tokens, int) and tokens >= 0:
            self.measured_tokens += tokens
            self.tokenized += 1

    def snapshot(self) -> dict:
        return {"spent_usd": round(self.measured_usd, 6) if self.calls and self.priced == self.calls else None,
                "tokens": self.measured_tokens if self.calls and self.tokenized == self.calls else None,
                "usage": {"calls": self.calls, "priced_calls": self.priced,
                          "measured_usd": round(self.measured_usd, 6),
                          "measured_tokens": self.measured_tokens,
                          "complete": bool(self.calls) and self.priced == self.calls and self.tokenized == self.calls}}
