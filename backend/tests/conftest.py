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
    claims_to_add = [
        {
            "id": "k9k_injector_failure_v1",
            "claim_key": "k9k_injector_failure",
            "title": "Injector failure on 1.5 dCi",
            "domain": "engine",
            "severity": "high",
            "confidence": 0.8,
            "status": "verified",
            "variants": ["megane4_k9k_90", "megane4_k9k_110"],
            "sources": [{"tier": "B", "source_url": "https://example.com", "quote": "injector"}]
        },
        {
            "id": "k9k_egr_clogging_v1",
            "claim_key": "k9k_egr_clogging",
            "title": "EGR valve clogging",
            "domain": "engine",
            "severity": "medium",
            "confidence": 0.7,
            "status": "verified",
            "variants": ["megane4_k9k_90", "megane4_k9k_110"],
            "sources": [{"tier": "B", "source_url": "https://example.com", "quote": "EGR"}]
        },
        {
            "id": "diesel_dpf_clogging_v1",
            "claim_key": "diesel_dpf_clogging",
            "title": "DPF particulate filter clogging",
            "domain": "emissions",
            "severity": "high",
            "confidence": 0.9,
            "status": "verified",
            "variants": ["megane4_k9k_90", "megane4_k9k_110", "megane4_r9m_130"],
            "sources": [{"tier": "A", "source_url": "https://example.com", "quote": "DPF"}]
        },
        {
            "id": "dc4_gearbox_shudder_v1",
            "claim_key": "dc4_gearbox_shudder",
            "title": "DC4 dry clutch EDC gearbox shudder",
            "domain": "transmission",
            "severity": "medium",
            "confidence": 0.8,
            "status": "verified",
            "variants": ["megane4_h5f_100", "megane4_h5f_130"],
            "sources": [{"tier": "A", "source_url": "https://example.com", "quote": "shudder"}]
        },
        {
            "id": "megane4_h5f_timingchain_v1",
            "claim_key": "megane4_h5f_timingchain",
            "title": "1.2 TCe H5F timing chain stretch",
            "domain": "engine",
            "severity": "high",
            "confidence": 0.8,
            "status": "verified",
            "variants": ["megane4_h5f_100", "megane4_h5f_130"],
            "sources": [{"tier": "A", "source_url": "https://example.com", "quote": "timing chain"}]
        }
    ]

    for row in claims_to_add:
        claim = Claim(
            id=row["id"],
            claim_key=row["claim_key"],
            version=1,
            is_current=True,
            title=row["title"],
            domain=row["domain"],
            severity=row["severity"],
            confidence=row["confidence"],
            rationale="Rationale",
            inspection_advice="Inspection advice",
            status=row["status"],
            kind="known_issue"
        )
        db.add(claim)
        db.flush()

        for v_id in row["variants"]:
            db.add(ClaimVariant(
                claim_id=claim.id,
                variant_id=v_id,
                grounding_note="test-mock"
            ))
        for s in row["sources"]:
            db.add(ClaimSource(
                claim_id=claim.id,
                tier=s["tier"],
                source_url=s["source_url"],
                quote=s["quote"],
                independent=True
            ))

    db.flush()
    # Also load part-centric claims via fitment assembly (same as sync_parts in production).
    sync_parts(db)
    db.flush()
    return claims_to_add
