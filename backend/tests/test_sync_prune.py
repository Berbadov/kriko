"""prune_removed_claims — claims absent from YAML stop serving on next sync.

sync is otherwise upsert-only; without prune a deleted/mis-grounded claim would
serve forever. The empty-seen guard must never wipe the table.
"""

from backend.db.models import Claim, ClaimSource, ClaimVariant
from backend.sync import prune_removed_claims


def _add_claim(db, cid, variant="megane4_k9k_90"):
    db.add(Claim(
        id=cid, claim_key=cid, version=1, is_current=True,
        title=cid, domain="engine", severity="low", confidence=0.6,
        rationale="r", inspection_advice="a", status="verified", promoted_by="human",
    ))
    db.add(ClaimVariant(claim_id=cid, variant_id=variant))
    db.add(ClaimSource(claim_id=cid, source_url="https://x", quote="q"))
    db.flush()


def test_prune_deletes_only_unseen(db, megane4_variants):
    _add_claim(db, "keep_v1")
    _add_claim(db, "gone_v1")

    n = prune_removed_claims(db, {"keep_v1"})
    db.flush()

    assert n == 1
    ids = {c.id for c in db.query(Claim).all()}
    assert ids == {"keep_v1"}


def test_empty_seen_ids_prunes_nothing(db, megane4_variants):
    """A failed/partial YAML load must not wipe the serving table."""
    _add_claim(db, "safe_v1")
    assert prune_removed_claims(db, set()) == 0
    assert db.query(Claim).count() == 1
