"""Token/cost accounting. Every LLM stage charges a Budget; --max-usd aborts
cleanly (BudgetExceeded) with the ledger intact and resumable."""

from datetime import datetime, timezone

# USD per million tokens: (input, output). Source: api-docs.deepseek.com/quick_start/pricing.
# deepseek-v4-flash actually has two input prices — $0.0028 cache-hit vs $0.14
# cache-miss — but Budget/estimate_cost only model one input price per model.
# We charge every input token at the (higher) cache-miss rate: a deliberate
# over-estimate so --max-usd stays a hard ceiling even when nothing caches,
# never an under-count that could let a run slip past budget.
PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "deepseek-v4-flash": (0.14, 0.28),
}


class BudgetExceeded(RuntimeError):
    pass


def estimate_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    p_in, p_out = PRICES_USD_PER_MTOK[model]
    return tokens_in * p_in / 1e6 + tokens_out * p_out / 1e6


class Budget:
    def __init__(self, max_usd: float | None = None):
        self.max_usd = max_usd
        self._by_model: dict[str, tuple[int, int, int, float]] = {}  # calls, tin, tout, usd

    @property
    def total_usd(self) -> float:
        return sum(v[3] for v in self._by_model.values())

    def charge(self, model: str, tokens_in: int, tokens_out: int) -> float:
        usd = estimate_cost(model, tokens_in, tokens_out)
        c, ti, to, u = self._by_model.get(model, (0, 0, 0, 0.0))
        self._by_model[model] = (c + 1, ti + tokens_in, to + tokens_out, u + usd)
        if self.max_usd is not None and self.total_usd > self.max_usd:
            raise BudgetExceeded(
                f"spent ${self.total_usd:.2f} > --max-usd ${self.max_usd:.2f}"
            )
        return usd

    def precheck(self, est_usd: float) -> None:
        """Raise BEFORE an unabortable spend (e.g. submitting a message batch)."""
        if self.max_usd is not None and self.total_usd + est_usd > self.max_usd:
            raise BudgetExceeded(
                f"planned +${est_usd:.2f} would exceed --max-usd ${self.max_usd:.2f}"
            )

    def report(self) -> str:
        lines = ["model                      calls   tok_in   tok_out      usd"]
        for m, (c, ti, to, u) in sorted(self._by_model.items()):
            lines.append(f"{m:<26} {c:>5} {ti:>8} {to:>9} {u:>8.4f}")
        lines.append(f"{'TOTAL':<26} {'':>5} {'':>8} {'':>9} {self.total_usd:>8.4f}")
        return "\n".join(lines)


def log_stage(conn, stage: str, model: str, calls: int,
              tokens_in: int, tokens_out: int, usd: float) -> None:
    conn.execute(
        "INSERT INTO runs (started_at, stage, model, calls, tokens_in, tokens_out, usd)"
        " VALUES (?,?,?,?,?,?,?)",
        (datetime.now(timezone.utc).isoformat(timespec="seconds"),
         stage, model, calls, tokens_in, tokens_out, usd),
    )
    conn.commit()
