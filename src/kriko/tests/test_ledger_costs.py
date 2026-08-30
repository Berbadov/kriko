import pytest

from kriko.ledger import costs, db


def test_charge_accumulates_and_reports():
    b = costs.Budget(max_usd=None)
    usd = b.charge("deepseek-v4-flash", 1_000_000, 0)
    assert usd == pytest.approx(0.14)
    b.charge("deepseek-v4-flash", 1_000_000, 1_000_000)
    assert b.total_usd == pytest.approx(0.14 + 0.14 + 0.28)
    assert "deepseek-v4-flash" in b.report()


def test_charge_raises_when_budget_exceeded():
    b = costs.Budget(max_usd=0.01)
    with pytest.raises(costs.BudgetExceeded):
        b.charge("deepseek-v4-flash", 100_000, 0)  # $0.014 > $0.01
    # the spend is still recorded so the report is honest
    assert b.total_usd == pytest.approx(0.014)


def test_precheck_blocks_before_spending():
    b = costs.Budget(max_usd=1.0)
    b.precheck(0.5)  # fine
    with pytest.raises(costs.BudgetExceeded):
        b.precheck(1.5)


def test_log_stage_writes_runs_row(tmp_path):
    conn = db.connect(tmp_path / "l.db")
    costs.log_stage(conn, "verdict", "deepseek-v4-flash", 3, 100, 50, 0.01)
    row = conn.execute("SELECT * FROM runs").fetchone()
    assert row["stage"] == "verdict" and row["calls"] == 3
