-- Kriko pack schema — one DDL, two uses.
--
-- The SAME schema is applied to a distributable pack file and to the local
-- installed store. Only which columns are populated differs (see the LOCAL ONLY
-- block at the bottom). That identity is deliberate: the exporter, the
-- installer, the CLI inspector and the test fixtures then share one set of
-- queries, and `kriko inspect some.kpack` is literally `kriko query` pointed at
-- a different file.
--
-- Two rules this file exists to enforce:
--
--   1. Slots are ROWS, not columns. There is no `variants` table with a
--      `displacement_cc` column, because that column is a claim that every
--      subject has an engine. An EV has no such row; a cordless drill has no
--      components at all. Both are ordinary cases here, not exceptions.
--
--   2. `pack_id` is in every primary key. Install is INSERT OR IGNORE,
--      uninstall is DELETE WHERE pack_id = ?, and no unique constraint spans
--      packs — so two packs can contradict each other and nothing is lost.
--
-- NOTE: there are deliberately NO append-only triggers here, unlike the
-- authoring ledger in knowledge/ledger/db.py. That ledger is a build cache with
-- provenance and must never lose a row. This store must support uninstall.
-- Merging the two would put those two facts in the same file.

PRAGMA foreign_keys = ON;

-- ── pack identity ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS packs (
  pack_id        TEXT PRIMARY KEY,   -- reverse-DNS, author-chosen: "org.kriko.cars"
  name           TEXT NOT NULL,
  version        TEXT NOT NULL,      -- semver
  schema_version INTEGER NOT NULL,
  built_at       TEXT NOT NULL,      -- ISO8601 UTC
  publisher      TEXT NOT NULL DEFAULT '',
  license        TEXT NOT NULL DEFAULT '',
  origin_url     TEXT NOT NULL DEFAULT '',
  content_digest TEXT NOT NULL,      -- sha256 over sorted row ids — NEVER over zip
                                     -- bytes, which vary with mtime and entry order
  manifest_json  TEXT NOT NULL DEFAULT '{}',
  -- LOCAL-ONLY: a distributed pack file leaves these at their defaults.
  enabled        INTEGER NOT NULL DEFAULT 1,
  installed_at   TEXT NOT NULL DEFAULT ''
);

-- ── vocabulary — attribute keys and predicates are DATA, not code ────────
-- This is the "puzzle inside the puzzle": a new category adds rows here, never
-- a Python dict. See CLAUDE.md's scalability principle.
CREATE TABLE IF NOT EXISTS terms (
  term_id    TEXT NOT NULL,       -- 'engine_code' | 'part_of' | 'usage_km' | 'engine/timing'
  pack_id    TEXT NOT NULL,
  role       TEXT NOT NULL,       -- attribute|predicate|subject_kind|enum_value|
                                  -- subsystem|domain|context_key
  datatype   TEXT NOT NULL DEFAULT 'text',   -- text|number|year|bool|enum
  unit       TEXT NOT NULL DEFAULT '',       -- km|cycles|hours|years|kwh|cc|hp
  parent_id  TEXT NOT NULL DEFAULT '',       -- taxonomy edge: 'engine/timing' -> 'engine'
  label_json TEXT NOT NULL DEFAULT '{}',     -- {"en":"Engine code","tr":"Motor kodu"}
  match_json TEXT NOT NULL DEFAULT '{}',     -- how lookup uses this term:
                                  -- {"required":true,"narrow_order":1,"tolerance":100}
  PRIMARY KEY (term_id, pack_id)
);

-- 'odometer' == 'mileage_km' is declared as data, so two packs that named the
-- same thing differently can still be reconciled without editing the engine.
CREATE TABLE IF NOT EXISTS term_aliases (
  term_id TEXT NOT NULL,
  pack_id TEXT NOT NULL,
  alias   TEXT NOT NULL,
  lang    TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (term_id, pack_id, alias, lang)
);

-- ── gate vocabulary — what a pack considers not worth surfacing ──────────
-- This is taste, and taste is a property of the category, so it is pack data
-- and never an engine constant. `pattern` is a literal phrase for covered,
-- generic and ambiguous, and a regular expression for noise and specificity.
CREATE TABLE IF NOT EXISTS gate_terms (
  pack_id TEXT NOT NULL,
  kind    TEXT NOT NULL,   -- covered|generic|ambiguous|noise|specificity
  pattern TEXT NOT NULL,
  note    TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (pack_id, kind, pattern)
);

-- ── subjects — the ONLY entity table ─────────────────────────────────────
-- A product, a variant, a component, or an aspect. A component is not a special
-- table; it is a subject with a `part_of` relation. A drill with no components
-- is therefore the degenerate case (zero relations), not a special case.
CREATE TABLE IF NOT EXISTS subjects (
  subject_id TEXT NOT NULL,       -- content hash of (kind, identity attributes)
  pack_id    TEXT NOT NULL,
  kind       TEXT NOT NULL,       -- a terms.term_id with role='subject_kind'
  label      TEXT NOT NULL,       -- display only — NEVER identity
  PRIMARY KEY (subject_id, pack_id)
);
CREATE INDEX IF NOT EXISTS idx_subjects_kind ON subjects(kind);

-- Tiered aliases: `attribution_safe` may be used to attribute evidence to this
-- subject; `search_only` may only widen a search query. Collapsing the two tiers
-- was design-flaw 3 — a search alias was allowed to attribute a claim.
--
-- `search_name` is the third tier and the narrowest: a complete phrase somebody
-- would type into a search box for exactly this subject. It attributes nothing
-- either, and it differs from `search_only` in being a whole name rather than a
-- fragment — `Volkswagen Golf 1.5 TSI` against `LXT`. Query templates render
-- these where a pack ships them and the display label where it does not,
-- because a display label carries whatever tells two rows apart in a list and
-- that is not the same string as one a person types: this pack's produced
-- `Volkswagen Golf 1.5_TSI 150 hp common problems`, which nobody has searched
-- for. A fragment must not become a query subject on its own (`LXT common
-- problems` is a worse search than the label), which is why this is a tier and
-- not a reuse of the one next to it.
CREATE TABLE IF NOT EXISTS subject_aliases (
  subject_id TEXT NOT NULL,
  pack_id    TEXT NOT NULL,
  alias      TEXT NOT NULL,
  lang       TEXT NOT NULL DEFAULT '',
  tier       TEXT NOT NULL DEFAULT 'attribution_safe',  -- attribution_safe|search_only|search_name
  PRIMARY KEY (subject_id, pack_id, alias, lang)
);

-- ── the row store — this replaces every column of the old `variants` ──────
CREATE TABLE IF NOT EXISTS attributes (
  attribute_id TEXT NOT NULL,     -- content hash
  pack_id      TEXT NOT NULL,
  subject_id   TEXT NOT NULL,
  key          TEXT NOT NULL,     -- terms.term_id, role='attribute'
  value_text   TEXT NOT NULL,     -- canonical string form, ALWAYS populated
  value_num    REAL,              -- also set when terms.datatype in (number, year),
                                  -- so range queries stay indexable
  unit         TEXT NOT NULL DEFAULT '',
  valid_from   TEXT NOT NULL DEFAULT '',  -- '' = unbounded. Replaces year_from/year_to.
  valid_to     TEXT NOT NULL DEFAULT '',
  is_identity  INTEGER NOT NULL DEFAULT 0,  -- participates in subject_id + matching
  confidence   REAL,
  -- Where the figure was read (B173). '' for identity keys and for packs built
  -- before the column existed; a spec shown to a reader carries one.
  source_url   TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (attribute_id, pack_id)
);
CREATE INDEX IF NOT EXISTS idx_attr_subject ON attributes(subject_id, key);
CREATE INDEX IF NOT EXISTS idx_attr_kv      ON attributes(key, value_text);
CREATE INDEX IF NOT EXISTS idx_attr_kn      ON attributes(key, value_num);

CREATE TABLE IF NOT EXISTS relations (
  relation_id TEXT NOT NULL,      -- content hash
  pack_id     TEXT NOT NULL,
  subject_id  TEXT NOT NULL,
  predicate   TEXT NOT NULL,      -- part_of|variant_of|same_as|made_by|supersedes
  object_id   TEXT NOT NULL,      -- another subject_id
  note        TEXT NOT NULL DEFAULT '',  -- why this edge exists (was grounding_note)
  PRIMARY KEY (relation_id, pack_id)
);
CREATE INDEX IF NOT EXISTS idx_rel_s ON relations(subject_id, predicate);
CREATE INDEX IF NOT EXISTS idx_rel_o ON relations(object_id, predicate);

-- ── claims ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS claims (
  claim_id    TEXT NOT NULL,      -- content hash
  pack_id     TEXT NOT NULL,
  subject_id  TEXT NOT NULL,      -- what it is about
  kind        TEXT NOT NULL,      -- known_issue|maintenance|recall|assessment
  domain      TEXT NOT NULL,      -- terms.term_id, role='domain'
  severity    TEXT NOT NULL,      -- high|medium|low
  consequence TEXT NOT NULL DEFAULT '',
  detection   TEXT NOT NULL DEFAULT '',  -- visual|test_drive|diagnostic|history_check
  -- Which sub-part of the subject the claim is about, and how to group it for
  -- display. Both are pack vocabulary (terms with role='component'/'subsystem'),
  -- not engine concepts — every manufactured product has sub-parts and every
  -- catalog wants them grouped. Kept as claim columns rather than as a finer
  -- subject because a component claim must reach the product through exactly
  -- one hop; making it a subject would need a second traversal direction, and
  -- that direction would also drag in sibling products sharing the same part.
  component   TEXT NOT NULL DEFAULT '',
  subsystem   TEXT NOT NULL DEFAULT '',
  -- The author's own confidence, carried through from the pipeline's verdict.
  -- The old `status` column (draft/review/verified) folds in here rather than
  -- being dropped: there is no authority to promote a claim, so review state
  -- becomes rank, not a gate. See backlog B26/B32.
  author_confidence REAL,
  created_at  TEXT NOT NULL,
  PRIMARY KEY (claim_id, pack_id)
);
CREATE INDEX IF NOT EXISTS idx_claims_subject ON claims(subject_id);

-- Language is a row, not a column. There is no title_tr/rationale_tr pair — a
-- pack may carry any number of languages, and two packs may contribute
-- translations of the same claim independently.
CREATE TABLE IF NOT EXISTS claim_text (
  claim_id TEXT NOT NULL,
  pack_id  TEXT NOT NULL,
  lang     TEXT NOT NULL,
  title    TEXT NOT NULL,
  body     TEXT NOT NULL DEFAULT '',        -- was `rationale`
  advice   TEXT NOT NULL DEFAULT '',        -- was `inspection_advice`
  PRIMARY KEY (claim_id, pack_id, lang)
);

-- The generic replacement for min_mileage_km, max_mileage_km, min_age_years,
-- applies_year_from/to, requires_equipment, maintenance_data, AND the five
-- car-specific compatibility gates that used to live in backend/sync.py.
-- Keyed by whatever usage term the pack declares: km for cars, charge cycles
-- for power tools, running hours for machines.
CREATE TABLE IF NOT EXISTS claim_conditions (
  claim_id   TEXT NOT NULL,
  pack_id    TEXT NOT NULL,
  seq        INTEGER NOT NULL,
  key        TEXT NOT NULL,       -- terms.term_id, role='context_key'
  op         TEXT NOT NULL,       -- gte|lte|eq|neq|in|has|mentions|interval
  value_text TEXT NOT NULL DEFAULT '',
  value_num  REAL,
  -- What to do when the reader cannot supply this context value. `open` is the
  -- fail-open default required by CLAUDE.md's automation principle: serve the
  -- claim, but downrank it by `weight` rather than hiding it or guessing.
  on_missing TEXT NOT NULL DEFAULT 'open',  -- open|closed|ignore
  weight     REAL NOT NULL DEFAULT 1.0,
  PRIMARY KEY (claim_id, pack_id, seq)
);

-- ── evidence ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sources (
  source_id       TEXT NOT NULL,   -- content hash of the normalised URL
  pack_id         TEXT NOT NULL,
  url             TEXT NOT NULL DEFAULT '',
  domain          TEXT NOT NULL DEFAULT '',
  site_or_channel TEXT NOT NULL DEFAULT '',
  title           TEXT NOT NULL DEFAULT '',
  lang            TEXT NOT NULL DEFAULT '',
  source_type     TEXT NOT NULL DEFAULT 'page',  -- page|video|structured|manual|dataset
  published_at    TEXT NOT NULL DEFAULT '',
  retrieved_at    TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (source_id, pack_id)
);

CREATE TABLE IF NOT EXISTS evidence (
  evidence_id TEXT NOT NULL,      -- content hash of (source, quote)
  pack_id     TEXT NOT NULL,
  claim_id    TEXT NOT NULL,
  source_id   TEXT NOT NULL,
  quote       TEXT NOT NULL,      -- verbatim
  locator     TEXT NOT NULL DEFAULT '',   -- char span | timestamp_s | page
  -- `refutes` is what makes "no authority" usable rather than merely stored:
  -- a contradicted claim still surfaces, ranked below, showing the rebuttal.
  stance      TEXT NOT NULL DEFAULT 'supports',  -- supports|refutes|qualifies
  independent INTEGER NOT NULL DEFAULT 1,
  PRIMARY KEY (evidence_id, pack_id)
);
CREATE INDEX IF NOT EXISTS idx_ev_claim ON evidence(claim_id);

-- ── trust — computed at READ time, never frozen into the claim row ───────
-- The old pipeline stamped source_tier/source_trust onto each claim at ETL
-- time, which made them unrevisable. Here the registry is unioned across
-- installed packs and the weights belong to the reader.
CREATE TABLE IF NOT EXISTS source_tiers (
  domain_pattern TEXT NOT NULL,
  pack_id        TEXT NOT NULL,
  tier           TEXT NOT NULL,   -- authoritative|manufacturer|specialist|forum_ugc|seo_blog
  note           TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (domain_pattern, pack_id)
);

CREATE TABLE IF NOT EXISTS tier_trust (
  tier    TEXT NOT NULL,
  pack_id TEXT NOT NULL,
  trust   REAL NOT NULL,          -- 0..1 relevance multiplier
  PRIMARY KEY (tier, pack_id)
);

-- ── pack assets — the non-tabular half of a pack ─────────────────────────
-- A pack is authored as a directory and shipped as ONE file, so everything the
-- directory holds that is not rows has to live somewhere: the value principle
-- the research stage prompts with, the search templates, the site adapter that
-- turns a scraped page into an identity. They are text, versioned with the pack
-- and readable by a person deciding whether to install it.
--
-- Deliberately NOT executable. A pack may ship a JSON adapter describing which
-- selectors to read; it may never ship code that runs in a browser or in the
-- MCP process. See the risks section of the design.
CREATE TABLE IF NOT EXISTS pack_assets (
  pack_id TEXT NOT NULL,
  name    TEXT NOT NULL,          -- 'principle.md' | 'templates.yaml' | 'adapters/x.json'
  kind    TEXT NOT NULL,          -- principle | templates | adapter | doc
  content TEXT NOT NULL,
  PRIMARY KEY (pack_id, name)
);

-- ── LOCAL ONLY — never present in a distributed pack file ────────────────
-- This table IS the "no authority" decision. Trust is not a property of the
-- data; it is the reader's subscription, the way an adblock filter list is.
CREATE TABLE IF NOT EXISTS pack_trust (
  pack_id TEXT PRIMARY KEY,
  weight  REAL NOT NULL DEFAULT 1.0,
  pinned  INTEGER NOT NULL DEFAULT 0   -- wins ties regardless of the trust maths
);

CREATE TABLE IF NOT EXISTS local_prefs (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL
);

-- ── local revision history ────────────────────────────────────────────────
-- `packs` is the active-read projection kept for backwards-compatible queries.
-- These tables make each installed content digest durable without adding a
-- revision column to every data row (which would change the public pack schema).
CREATE TABLE IF NOT EXISTS pack_revisions (
  revision_id  TEXT PRIMARY KEY,       -- pack_id + content digest
  pack_id      TEXT NOT NULL,
  version      TEXT NOT NULL,
  content_digest TEXT NOT NULL,
  name         TEXT NOT NULL,
  publisher    TEXT NOT NULL DEFAULT '',
  license      TEXT NOT NULL DEFAULT '',
  origin_url   TEXT NOT NULL DEFAULT '',
  manifest_json TEXT NOT NULL DEFAULT '{}',
  installed_at TEXT NOT NULL,
  activated_at TEXT NOT NULL DEFAULT '',
  UNIQUE (pack_id, content_digest)
);
CREATE INDEX IF NOT EXISTS idx_pack_revisions_pack ON pack_revisions(pack_id);

-- A JSON copy of the rows belonging to a revision. This is local-only state;
-- it lets rollback work after the original .kpack file has disappeared.
CREATE TABLE IF NOT EXISTS pack_revision_rows (
  revision_id TEXT NOT NULL,
  table_name  TEXT NOT NULL,
  row_key     INTEGER NOT NULL,
  row_json    TEXT NOT NULL,
  PRIMARY KEY (revision_id, table_name, row_key)
);

-- Expected row counts make a snapshot auditable: an empty table is valid, but
-- a missing final row in a non-empty table is not indistinguishable from empty.
CREATE TABLE IF NOT EXISTS pack_revision_tables (
  revision_id TEXT NOT NULL,
  table_name  TEXT NOT NULL,
  row_count   INTEGER NOT NULL,
  PRIMARY KEY (revision_id, table_name)
);

CREATE TABLE IF NOT EXISTS pack_events (
  event_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  pack_id       TEXT NOT NULL,
  action        TEXT NOT NULL,          -- install|update|activate|rollback|enable|disable|uninstall
  revision_id   TEXT NOT NULL DEFAULT '',
  version       TEXT NOT NULL DEFAULT '',
  content_digest TEXT NOT NULL DEFAULT '',
  created_at    TEXT NOT NULL,
  details_json  TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_pack_events_pack ON pack_events(pack_id, event_id);
