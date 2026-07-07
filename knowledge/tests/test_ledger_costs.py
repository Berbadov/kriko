import pytest
from knowledge.ledger import costs, db


def test_charge_accumulates_and_reports():
    b = costs.Budget(max_usd=None)
    usd = b.charge("ministral-8b-latest", 1_000_000, 0)
    assert usd == pytest.approx(0.10)
    b.charge("claude-haiku-4-5#batch", 1_000_000, 1_000_000)
    assert b.total_usd == pytest.approx(0.10 + 0.50 + 2.50)
    assert "ministral-8b-latest" in b.report()


def test_charge_raises_when_budget_exceeded():
    b = costs.Budget(max_usd=0.05)
    with pytest.raises(costs.BudgetExceeded):
        b.charge("claude-haiku-4-5", 100_000, 0)  # $0.10 > $0.05
    # the spend is still recorded so the report is honest
    assert b.total_usd == pytest.approx(0.10)


def test_precheck_blocks_before_spending():
    b = costs.Budget(max_usd=1.0)
    b.precheck(0.5)  # fine
    with pytest.raises(costs.BudgetExceeded):
        b.precheck(1.5)


def test_log_stage_writes_runs_row(tmp_path):
    conn = db.connect(tmp_path / "l.db")
    costs.log_stage(conn, "verdict", "claude-haiku-4-5", 3, 100, 50, 0.01)
    row = conn.execute("SELECT * FROM runs").fetchone()
    assert row["stage"] == "verdict" and row["calls"] == 3
