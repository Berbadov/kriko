-- Kriko DB schema — plain SQL, applied once at startup.
-- No migration framework until genuinely needed.
-- Run: psql $DATABASE_URL -f schema.sql

CREATE EXTENSION IF NOT EXISTS pgcrypto;  -- for gen_random_uuid()

CREATE TABLE IF NOT EXISTS variants (
  id               TEXT PRIMARY KEY,       -- "megane4_h5h_140"
  make             TEXT NOT NULL,
  model            TEXT NOT NULL,
  generation       TEXT,
  engine_code      TEXT,
  engine_family    TEXT,                   -- engineering family used as part-research key (e.g. k9k, h5h, ea211)
  fuel             TEXT NOT NULL,          -- "petrol" | "diesel" | "hybrid" | "electric"
  displacement_cc  INT,
  power_min_hp     INT,
  power_max_hp     INT,
  transmission     TEXT,                   -- "manual" | "automatic"
  transmission_code TEXT,                  -- revision-level gearbox code (e.g. edc, dq200, dq250)
  year_from        INT NOT NULL,
  year_to          INT,
  market           TEXT DEFAULT 'TR',
  notes            TEXT
);
CREATE INDEX IF NOT EXISTS idx_variants_lookup ON variants(make, model, fuel);

CREATE TABLE IF NOT EXISTS claims (
  id               TEXT PRIMARY KEY,       -- per-version ID
  claim_key        TEXT NOT NULL,          -- stable across versions
  version          INT NOT NULL DEFAULT 1,
  is_current       BOOLEAN NOT NULL DEFAULT true,
  title            TEXT NOT NULL,
  domain           TEXT NOT NULL,
  severity         TEXT NOT NULL,          -- "high" | "medium" | "low"
  confidence       REAL NOT NULL,          -- derived from tier + source_count
  rationale        TEXT NOT NULL,
  inspection_advice TEXT NOT NULL,
  status           TEXT NOT NULL DEFAULT 'draft', -- draft|verified|held|rejected
  promoted_by      TEXT,                   -- 'auto' | reviewer name
  created_at       TIMESTAMPTZ DEFAULT now(),
  -- Phase 1: context-aware gating
  kind             TEXT DEFAULT 'known_issue',  -- "known_issue"|"maintenance"|"recall"
  min_mileage_km   INT,
  max_mileage_km   INT,
  min_age_years    INT,
  -- Phase 2: maintenance-due claims
  maintenance_data JSONB,                  -- {interval_km, interval_years, evidence_keywords}
  -- Phase 3: offline relevance filter
  value_tier       TEXT                    -- "core"|"routine_inspection"|"generic_warning"
);

-- Migration: if the table already exists, add the new columns.
-- Run this manually on an existing production database:
-- ALTER TABLE variants ADD COLUMN IF NOT EXISTS engine_family TEXT;
-- ALTER TABLE variants ADD COLUMN IF NOT EXISTS transmission_code TEXT;
-- ALTER TABLE claims ADD COLUMN IF NOT EXISTS kind TEXT DEFAULT 'known_issue';
-- ALTER TABLE claims ADD COLUMN IF NOT EXISTS min_mileage_km INT;
-- ALTER TABLE claims ADD COLUMN IF NOT EXISTS max_mileage_km INT;
-- ALTER TABLE claims ADD COLUMN IF NOT EXISTS min_age_years INT;
-- ALTER TABLE claims ADD COLUMN IF NOT EXISTS maintenance_data JSONB;
-- ALTER TABLE claims ADD COLUMN IF NOT EXISTS value_tier TEXT;
CREATE INDEX IF NOT EXISTS idx_claims_serve ON claims(is_current, status);

CREATE TABLE IF NOT EXISTS claim_variants (
  claim_id    TEXT REFERENCES claims(id) ON DELETE CASCADE,
  variant_id  TEXT REFERENCES variants(id) ON DELETE CASCADE,
  grounding_note TEXT,                     -- WHY this claim attaches to this variant
  PRIMARY KEY (claim_id, variant_id)
);
CREATE INDEX IF NOT EXISTS idx_cv_variant ON claim_variants(variant_id);

CREATE TABLE IF NOT EXISTS claim_sources (
  id              SERIAL PRIMARY KEY,
  claim_id        TEXT REFERENCES claims(id) ON DELETE CASCADE,
  tier            TEXT NOT NULL,           -- 'A' | 'B' | 'C'
  source_url      TEXT NOT NULL,
  source_domain   TEXT,
  site_or_channel TEXT,
  title           TEXT,
  timestamp_s     INT,
  quote           TEXT NOT NULL,           -- verbatim, checked by judge
  independent     BOOLEAN DEFAULT true
);

CREATE TABLE IF NOT EXISTS analysis_log (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at           TIMESTAMPTZ DEFAULT now(),
  listing_url          TEXT,
  make                 TEXT,
  model                TEXT,
  year                 INT,
  fuel_type            TEXT,
  engine_cc            INT,
  power_hp             INT,
  transmission         TEXT,
  candidate_variant_ids TEXT[],
  matched_variant_ids  TEXT[],
  coverage_state       TEXT,
  match_method         TEXT,
  match_notes          TEXT,
  claim_ids_returned   TEXT[],
  claims_returned      INT,
  duration_ms          INT
);
