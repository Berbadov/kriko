from sqlalchemy import (
    Boolean, Column, Float, ForeignKey, Integer, JSON, String, Text, DateTime
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Variant(Base):
    __tablename__ = "variants"

    id                = Column(String, primary_key=True)
    make              = Column(String, nullable=False)
    model             = Column(String, nullable=False)
    generation        = Column(String)
    engine_code       = Column(String)
    engine_family     = Column(String)     # part-research key (k9k, h5h, ea211, …)
    fuel              = Column(String, nullable=False)
    displacement_cc   = Column(Integer)
    power_min_hp      = Column(Integer)
    power_max_hp      = Column(Integer)
    transmission      = Column(String)
    transmission_code = Column(String)     # revision-level gearbox code (edc, dq200, dq250, …)
    drivetrain        = Column(String)     # "fwd" | "awd" | "rwd" — catalog-fixed per variant/trim
    year_from         = Column(Integer, nullable=False)
    year_to           = Column(Integer)
    market            = Column(String, default="TR")
    notes             = Column(String)


class Claim(Base):
    __tablename__ = "claims"

    id                = Column(String, primary_key=True)
    claim_key         = Column(String, nullable=False)
    version           = Column(Integer, nullable=False, default=1)
    is_current        = Column(Boolean, nullable=False, default=True)
    title             = Column(String, nullable=False)
    domain            = Column(String, nullable=False)
    severity          = Column(String, nullable=False)
    confidence        = Column(Float, nullable=False)
    rationale         = Column(Text, nullable=False)
    inspection_advice = Column(Text, nullable=False)
    status            = Column(String, nullable=False, default="draft")
    promoted_by       = Column(String)
    created_at        = Column(DateTime)
    kind              = Column(String, nullable=True)   # "known_issue" | "maintenance" | "recall"
    min_mileage_km    = Column(Integer, nullable=True)
    max_mileage_km    = Column(Integer, nullable=True)
    min_age_years     = Column(Integer, nullable=True)
    applies_year_from = Column(Integer, nullable=True)  # inclusive model-year window (build-year defect scope)
    applies_year_to   = Column(Integer, nullable=True)  # inclusive upper bound; None = open-ended
    maintenance_data  = Column(JSON, nullable=True)    # the maintenance: block from YAML
    requires_equipment = Column(JSON, nullable=True)   # tags auto-derived from title/rationale, e.g. ["sunroof"]

    sources  = relationship("ClaimSource", back_populates="claim", cascade="all, delete-orphan")
    variants = relationship("ClaimVariant", back_populates="claim", cascade="all, delete-orphan")


class ClaimVariant(Base):
    __tablename__ = "claim_variants"

    claim_id       = Column(String, ForeignKey("claims.id", ondelete="CASCADE"), primary_key=True)
    variant_id     = Column(String, ForeignKey("variants.id", ondelete="CASCADE"), primary_key=True)
    grounding_note = Column(String)

    claim = relationship("Claim", back_populates="variants")


class ClaimSource(Base):
    __tablename__ = "claim_sources"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    claim_id        = Column(String, ForeignKey("claims.id", ondelete="CASCADE"))
    source_url      = Column(String, nullable=False)
    source_domain   = Column(String)
    site_or_channel = Column(String)
    title           = Column(String)
    timestamp_s     = Column(Integer)
    quote           = Column(Text, nullable=False)
    independent     = Column(Boolean, default=True)

    claim = relationship("Claim", back_populates="sources")


class AnalysisLog(Base):
    # Only used against Postgres in production. Tests skip this table entirely
    # (conftest.py only creates Variant/Claim/ClaimVariant/ClaimSource).
    __tablename__ = "analysis_log"

    id                    = Column(UUID(as_uuid=False), primary_key=True)
    created_at            = Column(DateTime)
    listing_url           = Column(String)
    make                  = Column(String)
    model                 = Column(String)
    year                  = Column(Integer)
    fuel_type             = Column(String)
    engine_cc             = Column(Integer)
    power_hp              = Column(Integer)
    transmission          = Column(String)
    candidate_variant_ids = Column(ARRAY(Text))
    matched_variant_ids   = Column(ARRAY(Text))
    coverage_state        = Column(String)
    match_method          = Column(String)
    match_notes           = Column(String)
    claim_ids_returned    = Column(ARRAY(Text))
    claims_returned       = Column(Integer)
    duration_ms           = Column(Integer)
