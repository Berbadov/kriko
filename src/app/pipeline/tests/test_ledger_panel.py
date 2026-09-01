"""ledger.panel — read-only pipeline + cost dashboard.

The spend/pending sections render the same numbers the budget caps enforce;
a test pins that with a small fixture DB so a schema or estimate regression
shows up as a failing render, not a surprise bill.
"""

from kriko.ledger import db
from app.pipeline import panel


def _seed(conn):
    conn.execute("INSERT INTO runs (started_at, stage, model, calls, tokens_in,"
                 " tokens_out, usd) VALUES ('t','extract','deepseek-v4-flash',"
                 "10,1000,2000,0.01)")
    conn.commit()


def test_spend_section_renders_runs(tmp_path):
    c = db.connect(tmp_path / "l.db")
    _seed(c)
    lines = panel.spend_section(c)
    text = "\n".join(lines)
    assert "extract" in text
    assert "deepseek-v4-flash" in text
    assert "$0.01" in text
    assert "TOTAL" in text


def test_pending_section_reports_cost_to_finish(tmp_path):
    c = db.connect(tmp_path / "l.db")
    lines = panel.pending_section(c)
    text = "\n".join(lines)
    assert "COST TO FINISH" in text
    assert "$" in text


def test_render_runs_end_to_end(tmp_path):
    c = db.connect(tmp_path / "l.db")
    out = panel.render(c, data_dir=tmp_path)
    assert "KRIKO PIPELINE PANEL" in out
    assert "1. SPEND" in out
    assert "5. GUARDRAILS" in out
    assert "remediate" in out
