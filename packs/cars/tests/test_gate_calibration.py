"""Calibration guard: the gate must not reject the bulk of the real catalog.

This replaces `packs/cars/pipeline/tests/test_agent_gates.py::
test_gates_do_not_reject_the_bulk_of_the_existing_catalog`, deleted along with
the orphaned `packs/cars/pipeline/agent/gates.py` it tested. That file's gate
logic is gone; the guard it carried is not optional to lose — it is the only
thing standing between a `gates.yaml` edit and silently rejecting half the
catalog, and `app.mcp_server.submit_findings` now enforces exactly this gate
at write time.

Vocabulary is loaded the production way: build the real cars pack, install it,
and read its rows with `kriko.gates.load_gates` — the same call
`submit_findings` makes, rather than the offline `_vocabulary()` shortcut
`packs/cars/pipeline/ledger/extraction.py` uses (which reads gates.yaml
directly and never applies `structural_reasons`). This test judges every
claim the same way `submit_findings` judges a submitted finding: `gate_reason`
first, then `structural_reasons` with `has_anchor` set from whatever the real
call site would have had — here, the part the claim already lives under
(`data["part_id"]`), the same anchor the deleted test used as its `hint`
argument to `check_evidence`.
"""

from pathlib import Path

import yaml

from kriko.gates import gate_reason, load_gates, structural_reasons
from kriko.store import packstore
from kriko.store.db import connect

PARTS_ROOT = Path(__file__).resolve().parents[1] / "data" / "parts"


def _vocab(tmp_path):
    from packs.cars import build

    out, _ = build.build(tmp_path / "cars.kpack")
    conn = connect(tmp_path / "store.sqlite")
    packstore.install(conn, out)
    vocab = load_gates(conn, "org.kriko.cars")
    conn.close()
    return vocab


def _rejected(title, rationale, has_anchor, vocab) -> bool:
    if gate_reason(f"{title} {rationale}", vocab):
        return True
    return bool(structural_reasons(title, rationale, vocab, has_anchor=has_anchor))


def test_gates_do_not_reject_the_bulk_of_the_existing_catalog(tmp_path):
    """A gate that fails good rows makes the agent path unusable. Pin the rate."""
    vocab = _vocab(tmp_path)

    total = rejected = 0
    for path in PARTS_ROOT.rglob("*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        has_anchor = bool(data.get("part_id"))
        for claim in data.get("claims") or []:
            total += 1
            if _rejected(
                claim.get("title", ""), claim.get("rationale", ""), has_anchor, vocab
            ):
                rejected += 1

    assert total > 100
    assert rejected / total < 0.05, f"{rejected}/{total} existing claims rejected"
