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
    if gate_reason(f"{title} {rationale}", vocab, subject=title, has_anchor=has_anchor):
        return True
    return bool(structural_reasons(title, rationale, vocab, has_anchor=has_anchor))


def _reason(title, rationale, has_anchor, vocab) -> str | None:
    """Which single rule rejected this claim, or None. For the per-kind guard."""
    reason = gate_reason(
        f"{title} {rationale}", vocab, subject=title, has_anchor=has_anchor
    )
    if reason:
        return reason
    if structural_reasons(title, rationale, vocab, has_anchor=has_anchor):
        return "structural"
    return None


def _measure_by_kind(vocab, *, has_anchor_from_part_id: bool):
    """Like `_measure`, but broken down by which single rule rejected a claim.

    The aggregate ceiling below (`< 0.05`) hides a whole rule regressing as
    long as the total stays under it — this is exactly how the `noise` bug
    got past calibration: it added ~2% of the corpus, comfortably under a 5%
    total ceiling that `covered` alone (before its own fix) already used up
    most of. A per-kind bound cannot hide one rule's regression inside
    another rule's margin.
    """
    total = 0
    counts = {"covered": 0, "generic": 0, "noise": 0, "ambiguous": 0, "structural": 0}
    for path in PARTS_ROOT.rglob("*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        has_anchor = has_anchor_from_part_id and bool(data.get("part_id"))
        for claim in data.get("claims") or []:
            total += 1
            reason = _reason(
                claim.get("title", ""), claim.get("rationale", ""), has_anchor, vocab
            )
            if reason:
                counts[reason] += 1
    return counts, total


def _measure(vocab, *, has_anchor_from_part_id: bool):
    """Walk the corpus once, judging every claim the way submit_findings does.

    ``has_anchor_from_part_id`` picks which real call-site shape to measure:
    True mirrors the deleted orphan's own calibration test (`hint=part_id`,
    always truthy in this corpus, so this is the best case — every claim
    behaves as if the agent had also supplied a `component`/`component_hint`).
    False mirrors the agent submitting a finding with neither field set, which
    it is free to do; `submit_findings` derives `has_anchor` only from those
    optional fields, never from the catalog's own `part_id`.
    """
    total = rejected = 0
    for path in PARTS_ROOT.rglob("*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        has_anchor = has_anchor_from_part_id and bool(data.get("part_id"))
        for claim in data.get("claims") or []:
            total += 1
            if _rejected(
                claim.get("title", ""), claim.get("rationale", ""), has_anchor, vocab
            ):
                rejected += 1
    return rejected, total


def test_gates_do_not_reject_the_bulk_of_the_existing_catalog(tmp_path):
    """A gate that fails good rows makes the agent path unusable. Pin the rate.

    Anchored: every claim gets `has_anchor=True`, exactly as the deleted
    orphan's own calibration test measured it (its `hint` argument was always
    the part_id, always truthy). This is a *floor* on the real agent-path
    rate, not an estimate of it — `submit_findings` derives `has_anchor` from
    an agent-supplied `component`/`component_hint` field that may be absent,
    never from the catalog's own part_id. The unanchored rate below measures
    the worse case where no agent finding carries that field at all; the true
    rate in production sits between the two, weighted by how often agents
    actually fill it in.
    """
    vocab = _vocab(tmp_path)

    rejected, total = _measure(vocab, has_anchor_from_part_id=True)
    assert total > 100
    assert rejected / total < 0.05, f"{rejected}/{total} existing claims rejected"


def test_the_unanchored_rejection_rate_is_measured_too(tmp_path):
    """The floor above is not the whole story — measure the worst case too.

    No ceiling is asserted here on purpose: nobody has set one for the
    unanchored case, and inventing one would be a guess dressed as a rule.
    What must not happen is this number going unmeasured and 3.29% (or
    whatever the anchored rate currently is) being mistaken for the real
    agent-path rate. If this number is surprising, that is the finding —
    report it rather than adding a threshold to make the test "pass" or
    "fail", neither of which this test claims to judge.
    """
    vocab = _vocab(tmp_path)

    rejected, total = _measure(vocab, has_anchor_from_part_id=False)
    assert total > 100
    # Sanity only — the gate must still keep the overwhelming majority of the
    # catalog even in the worst case, or something has gone badly wrong.
    assert rejected / total < 0.5, f"{rejected}/{total} existing claims rejected"


def test_each_gate_kind_is_bounded_on_its_own(tmp_path):
    """The aggregate 5% ceiling above cannot see one rule regressing.

    `noise` regressed to 14/699 (2.0%) while the aggregate (9/699, 1.29% at
    the time) sat comfortably under the 5% total ceiling — a per-kind bound
    is what would have caught it. These per-kind bounds are *measured*, not
    aspirational: each is the corpus's current count for that kind (measured
    2026-08-30, anchored case, 699 claims) with headroom, not a target to
    design toward. If a change legitimately moves a count, remeasure and move
    the bound — don't raise it reflexively to make a real regression pass.

      covered:    8/699 (1.14%) — bound 3%  (21 claims)
      generic:    0/699 (0.00%) — bound 2%  (14 claims)
      noise:      1/699 (0.14%) — bound 1%  (7 claims;  catches the 14-claim regression)
      ambiguous:  0/699 (0.00%) — bound 2%  (14 claims)
      structural: 0/699 (0.00%) — bound 2%  (14 claims)
    """
    vocab = _vocab(tmp_path)
    counts, total = _measure_by_kind(vocab, has_anchor_from_part_id=True)
    assert total > 100

    bounds = {
        "covered": 0.03,
        "generic": 0.02,
        "noise": 0.01,
        "ambiguous": 0.02,
        "structural": 0.02,
    }
    for kind, bound in bounds.items():
        rate = counts[kind] / total
        assert rate < bound, (
            f"{kind}: {counts[kind]}/{total} ({rate:.2%}) exceeds its bound "
            f"of {bound:.0%} — the aggregate ceiling would not have caught "
            "this on its own"
        )
