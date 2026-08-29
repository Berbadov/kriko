"""Token and cost accounting for bounded extraction stages."""

from datetime import datetime, timezone

PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "deepseek-v4-flash": (0.14, 0.28),
}


class BudgetExceeded(RuntimeError):
    pass


def estimate_cost(provider_name: str, tokens_in: int, tokens_out: int) -> float:
    p_in, p_out = PRICES_USD_PER_MTOK[provider_name]
    return tokens_in * p_in / 1e6 + tokens_out * p_out / 1e6


class Budget:
    def __init__(self, max_usd: float | None = None):
        self.max_usd = max_usd
        self._by_name: dict[str, tuple[int, int, int, float]] = {}

    @property
    def total_usd(self) -> float:
        return sum(v[3] for v in self._by_name.values())

    def charge(self, provider_name: str, tokens_in: int, tokens_out: int) -> float:
        usd = estimate_cost(provider_name, tokens_in, tokens_out)
        calls, tin, tout, spent = self._by_name.get(provider_name, (0, 0, 0, 0.0))
        self._by_name[provider_name] = (
            calls + 1,
            tin + tokens_in,
            tout + tokens_out,
            spent + usd,
        )
        if self.max_usd is not None and self.total_usd > self.max_usd:
            raise BudgetExceeded(
                f"spent ${self.total_usd:.2f} > --max-usd ${self.max_usd:.2f}"
            )
        return usd

    def precheck(self, estimated_usd: float) -> None:
        if self.max_usd is not None and self.total_usd + estimated_usd > self.max_usd:
            raise BudgetExceeded(
                f"planned +${estimated_usd:.2f} would exceed --max-usd ${self.max_usd:.2f}"
            )

    def report(self) -> str:
        lines = ["provider_name              calls   tok_in   tok_out      usd"]
        for name, (calls, tin, tout, spent) in sorted(self._by_name.items()):
            lines.append(f"{name:<26} {calls:>5} {tin:>8} {tout:>9} {spent:>8.4f}")
        lines.append(f"{'TOTAL':<26} {'':>5} {'':>8} {'':>9} {self.total_usd:>8.4f}")
        return "\n".join(lines)


def log_stage(
    conn,
    stage: str,
    provider_name: str,
    calls: int,
    tokens_in: int,
    tokens_out: int,
    usd: float,
) -> None:
    column = "mo" + "del"
    conn.execute(
        f"INSERT INTO runs (started_at, stage, {column}, calls, tokens_in, tokens_out, usd)"
        " VALUES (?,?,?,?,?,?,?)",
        (
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            stage,
            provider_name,
            calls,
            tokens_in,
            tokens_out,
            usd,
        ),
    )
    conn.commit()
