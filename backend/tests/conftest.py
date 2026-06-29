"""Shared pytest fixtures.

Uses an in-memory SQLite database so tests run without a live Postgres.
analysis_log is excluded (it has Postgres-specific ARRAY types not needed here).
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.db.models import Base, Claim, ClaimSource, ClaimVariant, Variant
from backend.sync import sync_parts


@pytest.fixture(scope="session")
def engine_fixture():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    # Create only the tables the matcher/resolver use — skip analysis_log.
    for table in [Variant.__table__, Claim.__table__, ClaimVariant.__table__, ClaimSource.__table__]:
        table.create(eng, checkfirst=True)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine_fixture):
    """Fresh transactional session per test — rolled back after each test."""
    with Session(engine_fixture) as session:
        yield session
        session.rollback()


@pytest.fixture
def megane4_variants(db):
    """Load Renault Megane IV variants from YAML into the test DB."""
    import yaml
    from pathlib import Path

    path = Path(__file__).parent.parent / "data" / "variants" / "renault_megane_4.yaml"
    rows = yaml.safe_load(path.read_text())
    for row in rows:
        v = Variant(**row)
        db.add(v)
    db.flush()
    return rows


@pytest.fixture
def megane4_claims(db, megane4_variants):
    """Load Megane IV seed claims into the test DB."""
    import yaml
    from pathlib import Path

    path = Path(__file__).parent.parent / "data" / "claims" / "renault_megane_4.yaml"
    rows = yaml.safe_load(path.read_text())
    for row in rows:
        applies_when = row.get("applies_when") or {}
        claim = Claim(
            id=row["id"],
            claim_key=row["claim_key"],
            version=row.get("version", 1),
            is_current=row.get("is_current", True),
            title=row["title"],
            domain=row["domain"],
            severity=row["severity"],
            confidence=row["confidence"],
            rationale=row["rationale"].strip(),
            inspection_advice=row["inspection_advice"].strip(),
            status=row.get("status", "draft"),
            promoted_by=row.get("promoted_by"),
            kind=row.get("kind", "known_issue"),
            min_mileage_km=applies_when.get("min_mileage_km"),
            max_mileage_km=applies_when.get("max_mileage_km"),
            min_age_years=applies_when.get("min_age_years"),
            maintenance_data=row.get("maintenance"),
            value_tier=row.get("value_tier"),
        )
        db.add(claim)
        db.flush()

        for v in row.get("variants", []):
            db.add(ClaimVariant(
                claim_id=claim.id,
                variant_id=v["variant_id"],
                grounding_note=v.get("grounding_note"),
            ))
        for s in row.get("sources", []):
            db.add(ClaimSource(
                claim_id=claim.id,
                tier=s["tier"],
                source_url=s["source_url"],
                source_domain=s.get("source_domain"),
                site_or_channel=s.get("site_or_channel"),
                title=s.get("title"),
                quote=s["quote"].strip(),
                independent=s.get("independent", True),
            ))
    db.flush()
    # Also load part-centric claims via fitment assembly (same as sync_parts in production).
    # Claims migrated from the legacy flat YAML now live in backend/data/parts/*.yaml
    # and are assembled into variant links by the fitment YAML.
    sync_parts(db)
    db.flush()
    return rows
