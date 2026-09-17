"""UI state: lookup history and interface settings.

This is `app/`'s own SQLite file, `~/.kriko/app.sqlite`, deliberately separate
from the engine's `knowledge.sqlite`. The engine's schema is its contract with
pack authors — every table in it is something a pack writes or a ranker reads.
A `lookups` table there would be the first one nobody in `kriko/` uses, and the
precedent that admits the next one.

Two consequences settle it: uninstalling a pack must not drop your history, and
a history row must never affect a pack's `content_digest`.
"""

import json
import re
import secrets
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from app import factcheck
from kriko.store.db import schema_stamp

SCHEMA = """
CREATE TABLE IF NOT EXISTS lookups (
    lookup_id     TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    source        TEXT NOT NULL,
    label         TEXT NOT NULL,
    request_json  TEXT NOT NULL,
    response_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS lookups_created_at ON lookups (created_at DESC);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Sightings of the browser extension, keyed by the origin the browser
-- stamped on the request. A `chrome-extension://<id>` origin cannot be
-- forged by a config file or asserted by a reader who thinks they installed
-- it: it means an extension exists, is running, and reached this process.
-- That is the only evidence the app has that the install actually worked,
-- and it is why the extension page is a status rather than instructions.
-- Per-origin rather than one row, because two browser profiles get two ids
-- and "which of my browsers is wired up" is the question that follows.
CREATE TABLE IF NOT EXISTS extension_seen (
    origin   TEXT PRIMARY KEY,
    first_at TEXT NOT NULL,
    last_at  TEXT NOT NULL,
    hits     INTEGER NOT NULL DEFAULT 1,
    -- What the extension says it is. Blank for a version that predates the
    -- header, which is itself the answer to "how old is it" — an extension
    -- too old to say is older than every extension that says anything. The
    -- default is what lets this be added to an existing file at all; see
    -- `add_missing_columns`.
    version  TEXT NOT NULL DEFAULT ''
);

-- Triage: which claims of a stored answer the reader has dealt with.
-- Keyed by (lookup_id, claim_key) rather than by claim_id, because an
-- /api/analyze payload has no claim_id and the reader's checkmark must
-- survive anyway. The key is whatever the UI can compute from a claim it
-- has in hand; the engine never sees it.
-- Long work, as rows first and a stream second. A job that exists only in a
-- thread cannot be recovered after a restart, and "a spinner that never
-- resolves" is the failure mode this table exists to make impossible.
CREATE TABLE IF NOT EXISTS jobs (
    job_id           TEXT PRIMARY KEY,
    kind             TEXT NOT NULL,
    params_json      TEXT NOT NULL,
    state            TEXT NOT NULL,
    progress         REAL NOT NULL DEFAULT 0,
    message          TEXT NOT NULL DEFAULT '',
    log              TEXT NOT NULL DEFAULT '',
    result_json      TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    started_at       TEXT,
    finished_at      TEXT
);
CREATE INDEX IF NOT EXISTS jobs_created_at ON jobs (created_at DESC);

CREATE TABLE IF NOT EXISTS claim_checks (
    lookup_id  TEXT NOT NULL,
    claim_key  TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (lookup_id, claim_key)
);

-- What the seller said. The other half of triage: a checkmark records that
-- the reader dealt with a risk, and this records *how it went* — "belt done
-- at 140k, no receipt" is the sentence that turns a report into a record of
-- a negotiation, and it is the thing they will want on the second visit.
--
-- Its own table rather than a column on `claim_checks`, for a mechanical
-- reason: `connect()` re-runs SCHEMA when its fingerprint moves, and every
-- statement in it is CREATE TABLE IF NOT EXISTS — a new table therefore
-- migrates itself, while a new *column* on an existing table would not.
-- Keeping them apart also keeps `claim_checks` honest: a row there means
-- handled, and a note is not a checkmark.
CREATE TABLE IF NOT EXISTS claim_notes (
    lookup_id  TEXT NOT NULL,
    claim_key  TEXT NOT NULL,
    note       TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (lookup_id, claim_key)
);

-- What the reader thought of a claim, as opposed to whether they have dealt
-- with it in one answer (`claim_checks`, above). A mark is about the claim
-- itself: "this was wrong about my car" stays true on the next listing, so it
-- is keyed by the pack's claim identity rather than by a lookup.
--
-- Interface state, not engine state, for the reason at the top of this file:
-- a reader's opinion must not change a pack's `content_digest`, and
-- uninstalling a pack must not erase what they said about it. That also makes
-- this the honest place for it — an opinion is not evidence, and the engine's
-- schema is for things a pack writes or a ranker reads.
--
-- `subject_id` and `title` are copied in rather than joined out. A pack
-- updates weekly and can be uninstalled; a mark whose claim row has since
-- gone must still be readable, or the reader's own notes turn into a list of
-- hashes. This is a snapshot on purpose, and it is why the copy is not a
-- normalisation bug.
CREATE TABLE IF NOT EXISTS claim_marks (
    pack_id    TEXT NOT NULL,
    claim_id   TEXT NOT NULL,
    verdict    TEXT NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    subject_id TEXT NOT NULL DEFAULT '',
    title      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (pack_id, claim_id)
);
CREATE INDEX IF NOT EXISTS claim_marks_updated ON claim_marks (updated_at DESC);

-- What a researcher submitted, and what happened to it.
--
-- `app/findings.py` refuses most of what arrives — ungrounded quotes, generic
-- items, claims anchored to nothing — and until this table those refusals were
-- returned to the caller and then dropped on the floor. They are the highest
-- signal this project produces: a refusal names, in the gate's own words, the
-- thing the agent skill failed to ask for. An author who cannot read them is
-- tuning the skill blind.
--
-- Interface state, deliberately, for the reason at the top of this file: a
-- refused finding is not pack content and must not touch a `content_digest`.
-- It is also why `door` is recorded — MCP and the in-app research job share
-- one acceptance path, and the first question about a bad batch is which of
-- them produced it.
-- The last time a claim's evidence was re-read, and what the page said then.
--
-- `app/factcheck.py` holds the reasoning; the reason the row is *here* is the
-- one at the top of this file. A re-check is an observation this interface
-- made about a page on the open web — not something a pack wrote, and not
-- something a ranker may read. If it lived in the engine's store, a dead link
-- would change a `content_digest`, and one reader's fetch failure would
-- travel to everyone who installs the pack next.
--
-- One row per claim, replaced: "what does the source say now" has exactly one
-- current answer, and a log of every press is a table nobody reads. `title`
-- and `subject_id` are snapshots for the same reason `claim_marks` snapshots
-- them — the pack that carried the claim can be updated or removed.
CREATE TABLE IF NOT EXISTS fact_checks (
    pack_id    TEXT NOT NULL,
    claim_id   TEXT NOT NULL,
    verdict    TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT '',
    sources_json TEXT NOT NULL DEFAULT '[]',
    subject_id TEXT NOT NULL DEFAULT '',
    title      TEXT NOT NULL DEFAULT '',
    checked_at TEXT NOT NULL,
    PRIMARY KEY (pack_id, claim_id)
);
CREATE INDEX IF NOT EXISTS fact_checks_checked ON fact_checks (checked_at DESC);

CREATE TABLE IF NOT EXISTS submissions (
    submission_id TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    door          TEXT NOT NULL,
    subject_id    TEXT NOT NULL,
    pack_id       TEXT NOT NULL,
    accepted      INTEGER NOT NULL DEFAULT 0,
    refused       INTEGER NOT NULL DEFAULT 0,
    verdicts_json TEXT NOT NULL,
    -- The searches that actually produced this batch (B95). Defaulted rather
    -- than required because the column arrived after the table did, and
    -- `add_missing_columns` can only add a column that has a default: an
    -- older installation's rows stay readable and simply say nothing about
    -- which queries they came from, which is the truth about them.
    queries_json  TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS submissions_created ON submissions (created_at DESC);

-- ── the knowledge pipeline, as rows ──────────────────────────────────────
--
-- A `jobs` row already says whether long work is running, how far along it
-- claims to be, and what it printed. What it cannot say is *what the pipeline
-- did*: which stage, how many sources, how much text, what was kept, what was
-- refused and why. So the Console showed a log and the reader had no way to
-- tell a research run that found nothing from one that found plenty and threw
-- it all away at the grounding check — two completely different situations
-- with the same-looking output.
--
-- Three tables, because there are three questions with three lifetimes:
-- "what runs have there been" (a run, kept), "how did this one move through
-- the stages" (a stage, kept), and "what happened inside a stage" (an event,
-- pruned). Rolling them into one would either lose the stage summary to event
-- volume or force a rewrite of the run row on every event.
--
-- Interface state, for the same reason `submissions` is: none of this is pack
-- content, so none of it may touch a `content_digest`. And it is a row before
-- it is a stream — a run interrupted by a restart must be *readable*
-- afterwards, which is the whole lesson of the jobs table.
CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id      TEXT PRIMARY KEY,
    -- The job this run belongs to, when there is one. Nullable because a run
    -- may be driven from the CLI or MCP, which have no job row.
    job_id      TEXT,
    kind        TEXT NOT NULL,          -- research | pack_build
    subject_id  TEXT NOT NULL DEFAULT '',
    subject     TEXT NOT NULL DEFAULT '',
    pack_id     TEXT NOT NULL DEFAULT '',
    plane       TEXT NOT NULL DEFAULT '',
    state       TEXT NOT NULL,          -- running | done | failed | interrupted
    -- Totals, denormalised on purpose: the overview lists runs and must not
    -- aggregate thousands of events to render a row.
    sources     INTEGER NOT NULL DEFAULT 0,
    findings    INTEGER NOT NULL DEFAULT 0,
    accepted    INTEGER NOT NULL DEFAULT 0,
    refused     INTEGER NOT NULL DEFAULT 0,
    chars       INTEGER NOT NULL DEFAULT 0,
    -- Reported by the plane when it spends tokens, and left NULL when nobody
    -- counted. NULL and 0 are different answers and the UI says which: the
    -- agent plane's marginal cost really is zero, and an estimate presented as
    -- a measurement is the `raised: true` mistake again.
    tokens      INTEGER,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    error       TEXT
);
CREATE INDEX IF NOT EXISTS pipeline_runs_started ON pipeline_runs (started_at DESC);

-- One row per stage per run, created when the stage opens so a stage that
-- never finished is visible as exactly that rather than as an absence.
CREATE TABLE IF NOT EXISTS pipeline_stages (
    run_id     TEXT NOT NULL,
    stage      TEXT NOT NULL,           -- see pipeline.STAGES
    seq        INTEGER NOT NULL,        -- display order, from STAGES
    state      TEXT NOT NULL,           -- running | done | failed | skipped
    detail     TEXT NOT NULL DEFAULT '',
    items      INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    ended_at   TEXT,
    PRIMARY KEY (run_id, stage)
);

-- What happened inside a stage. High volume, so it is the one table that is
-- pruned — and pruned by run rather than by age, because half an event log is
-- more misleading than none.
CREATE TABLE IF NOT EXISTS pipeline_events (
    event_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL,
    stage      TEXT NOT NULL,
    at         TEXT NOT NULL,
    level      TEXT NOT NULL DEFAULT 'info',   -- info | kept | refused | warn
    message    TEXT NOT NULL,
    -- The originating source, when the event has one. This is what makes a
    -- live view of "what is being read right now, and what came out of it"
    -- possible at all.
    source_url TEXT NOT NULL DEFAULT '',
    detail_json TEXT
);
CREATE INDEX IF NOT EXISTS pipeline_events_run ON pipeline_events (run_id, event_id);

-- ── labels no adapter reads ──────────────────────────────────────────────
--
-- `adapt()` already computes them: every label the page carried that no
-- adapter rule covers. Until now the number was handed to the caller and
-- thrown away, which made the one signal that a site has changed its markup
-- the one signal nobody could see.
--
-- What that costs: a listing site renames "Motor Hacmi" and the adapter stops
-- reading engine size. Nothing errors. The lookup still succeeds, resolves
-- less precisely, and returns fewer claims — so the failure arrives as
-- knowledge quietly going missing, which is indistinguishable from a thin
-- pack. The label was in the response the whole time.
--
-- Accumulated rather than appended, one row per (adapter, label): a label on
-- a template appears on every listing of that type, and a log of every
-- sighting would be a table that grows with reading volume while answering a
-- question about *distinct* labels. `seen` is the weight, `last_seen` is what
-- separates "the site changed last week" from "this was odd once in June".
--
-- Interface state, deliberately: a pack's adapter is content, and what a
-- reader's browsing happened to reveal about a site is not. It must never
-- reach a `content_digest`, and clearing your history must not erase it —
-- which is why it is its own table rather than a column on `lookups`.
CREATE TABLE IF NOT EXISTS unmapped_labels (
    adapter_id TEXT NOT NULL,
    label      TEXT NOT NULL,
    seen       INTEGER NOT NULL DEFAULT 0,
    first_at   TEXT NOT NULL,
    last_at    TEXT NOT NULL,
    -- One example, overwritten. Enough to open the page and look; not a list,
    -- because a reader debugging an adapter needs one URL and a count, not
    -- every URL that had the label.
    sample_url TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (adapter_id, label)
);
CREATE INDEX IF NOT EXISTS unmapped_labels_last ON unmapped_labels (last_at DESC);

-- ── who researched this, with what, and what it cost ─────────────────────
--
-- `pipeline_runs` already answers "what happened in this run". These two
-- tables answer the different question a reader asks *afterwards*: which of
-- my claims came from the paid plane, which model wrote them, and can I take
-- them back out.
--
-- **In app.sqlite, and that is the load-bearing decision.** A claim's own
-- evidence chain — its quote, its source URL, its confidence — belongs to the
-- pack and lives in the engine store, because it is what makes the claim
-- checkable by anyone. *Who ran the research* is not: it is a fact about this
-- installation. Putting it in the engine schema would make a pack's
-- `content_digest` depend on which machine grew it, and pack-update refusal is
-- built entirely on two installations computing the same digest for the same
-- version. Two readers who researched the same subject would then disagree
-- about whether an update is a republish.
CREATE TABLE IF NOT EXISTS research_runs (
    -- The same id `pipeline_runs` uses, so Activity joins the two without a
    -- second identifier for one run.
    run_id          TEXT PRIMARY KEY,
    job_id          TEXT,
    -- `agent` | `api`. Not "provider": the plane is what determines whether
    -- anything left this machine.
    plane           TEXT NOT NULL DEFAULT '',
    -- Named, not inferred. "researched by an LLM" is not a provenance record;
    -- "gpt-4o-mini via api.openai.com, searched with Exa" is one. Empty on the
    -- agent plane, where the model is whatever harness the reader was using
    -- and this process genuinely does not know.
    model           TEXT NOT NULL DEFAULT '',
    search_provider TEXT NOT NULL DEFAULT '',
    -- The ceiling and the actual, both. A run that stopped because it hit the
    -- ceiling and a run that finished under it look identical without the pair.
    budget_usd      REAL,
    spent_usd       REAL,
    -- Tokens, when the plane can count them, and NULL when it cannot — the
    -- same distinction `spent_usd` keeps, for the same reason. Dollars and
    -- tokens are separate measurements rather than one derived from the
    -- other: the harness plane knows its tokens and costs the reader nothing
    -- beyond a subscription, and a per-call price knows its dollars without
    -- ever seeing a token. Added after the table existed, so it has no NOT
    -- NULL and no default: see `add_missing_columns`.
    tokens_used     INTEGER,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    -- done | cancelled | budget | failed. `budget` is deliberately not
    -- `failed`: a hard stop working is not a fault, and colouring it as one
    -- teaches the reader to ignore the colour.
    outcome         TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS research_runs_started ON research_runs (started_at DESC);

-- What a run added, so it can be taken back out. One row per accepted claim.
--
-- Undo is why this exists, and undo is why it is per-claim rather than a count:
-- "this run added 6 claims" cannot be reversed, and a reader who accepted a
-- run they later distrust needs the reversal, not the number.
CREATE TABLE IF NOT EXISTS research_run_claims (
    run_id     TEXT NOT NULL,
    pack_id    TEXT NOT NULL,
    claim_id   TEXT NOT NULL,
    subject_id TEXT NOT NULL DEFAULT '',
    title      TEXT NOT NULL DEFAULT '',
    -- Set when an undo has taken this claim back out, so a second undo of the
    -- same run is a no-op that can say so rather than a silent success.
    removed_at TEXT,
    PRIMARY KEY (run_id, pack_id, claim_id)
);
CREATE INDEX IF NOT EXISTS research_run_claims_claim
    ON research_run_claims (pack_id, claim_id);

-- ── the text a quote was proved against ──────────────────────────────────
--
-- The evidence chain is this product's one hard guarantee: a quote that is
-- not in the document does not become evidence. `app/findings.py` makes that
-- check mechanically, once — and until this table it made it against text
-- nobody kept. So the guarantee was true at acceptance and unrepeatable
-- afterwards: a page that changes or dies takes the only copy with it, two
-- findings from one page cannot be cross-checked against each other, and
-- "was this source ever actually fetched" — which B112 needs in order to
-- recognise a fabricated `source_url` — had no answer at all.
--
-- **Here rather than in the engine's store**, by the rule at the top of this
-- file. A document is how *this installation* came to believe a claim, not
-- part of the knowledge a pack ships: a published pack carries the quote and
-- the URL, which is what a downstream consumer re-checks. Putting the page
-- text in `knowledge.sqlite` would put it inside a pack's `content_digest`,
-- so two readers who researched the same subject would compute different
-- digests for the same version and every pack update would look like a
-- republish.
--
-- Keyed by `source_id`, which is what `evidence` already points at, so a
-- claim reaches its document through the row it already has. One row per
-- source, replaced: two findings quoting one page submit the same text
-- twice, and a second copy answers no question the first cannot.
CREATE TABLE IF NOT EXISTS documents (
    source_id   TEXT PRIMARY KEY,
    pack_id     TEXT NOT NULL DEFAULT '',
    url         TEXT NOT NULL DEFAULT '',
    -- The text itself, or empty when the page was larger than
    -- MAX_DOCUMENT_CHARS. Empty text with a non-zero `chars` is therefore a
    -- third answer — "this source was fetched and is not kept" — and it is
    -- deliberately not a truncation: half a page would re-check as
    -- `ungrounded` for a quote that was genuinely in the other half, which is
    -- the one wrong answer this table must never produce.
    text        TEXT NOT NULL DEFAULT '',
    chars       INTEGER NOT NULL DEFAULT 0,
    -- Defaulted, though this writer always supplies it: every column in this
    -- file carries one so that `add_missing_columns` can always do its job,
    -- and a column that is only addable while its table is new is a trap for
    -- whoever adds the next one.
    retained_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS documents_retained ON documents (retained_at DESC);

-- ── operations: what an agent is doing, whichever door it came in ────────
--
-- An *operation* is one unit of agent-driven work on the knowledge (see
-- `docs/AGENT_OPERATIONS.md`). B121 made a run Kriko *starts* visible while it
-- runs; this is the other half, and the bigger one — the door the reader
-- actually prefers is their own coding agent talking to the MCP server, and
-- that door was visible only afterwards, as a `submissions` row, and only when
-- the operation happened to be a submission. A `lookup`, a `research_brief`, a
-- `draft_pack` left no trace at all.
--
-- One row per call, opened when it starts and closed when it ends, so a call
-- that is *still running* is a row rather than an absence: that is the whole
-- difference between a feed and a log.
--
-- Interface state, for the reason at the top of this file: what an agent asked
-- this installation is not pack content and must never reach a
-- `content_digest`.
--
-- `request_json` and `response_json` are **summaries, not payloads**. A
-- `submit_findings` call carries whole pages of `document_text`; storing them
-- here would duplicate the `documents` table and make this the largest thing
-- in the file. `app/operations.py` elides them and says how many characters it
-- dropped.
CREATE TABLE IF NOT EXISTS operations (
    op_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    -- mcp | job | http | cli. Which door, because "who did this" is the first
    -- question about anything surprising in this table.
    door         TEXT NOT NULL DEFAULT '',
    -- The operation vocabulary: research | agenda | author | recheck | read |
    -- write. Coarser than `name` on purpose — a feed filtered by kind answers
    -- "is anything growing the knowledge right now", which a list of nineteen
    -- tool names does not.
    kind         TEXT NOT NULL DEFAULT '',
    -- The tool or endpoint as it is actually called, e.g. `submit_findings`.
    name         TEXT NOT NULL DEFAULT '',
    subject_id   TEXT NOT NULL DEFAULT '',
    pack_id      TEXT NOT NULL DEFAULT '',
    state        TEXT NOT NULL DEFAULT 'running',   -- running | ok | failed
    request_json  TEXT NOT NULL DEFAULT '',
    response_json TEXT NOT NULL DEFAULT '',
    error        TEXT NOT NULL DEFAULT '',
    ms           INTEGER,
    started_at   TEXT NOT NULL DEFAULT '',
    ended_at     TEXT NOT NULL DEFAULT '',
    -- What this one call spent, when it spent anything (B118). NULL where
    -- nobody counted, never 0 — the same distinction `research_runs` and
    -- `bench_runs` keep, for the same reason: an MCP `lookup` costs nothing
    -- and a `research` operation on the paid plane knows a real number, and
    -- averaging the first in as free would understate every estimate built on
    -- the second. Added after the table existed, hence no default beyond
    -- NULL (see `add_missing_columns`).
    usd          REAL,
    tokens       INTEGER
);
CREATE INDEX IF NOT EXISTS operations_started ON operations (op_id DESC);

-- ── the benchmark: the same case, every plane, measured ──────────────────
--
-- B111, and it is the input B123 cannot invent. Choosing how an operation
-- should spend a model — how much context per call, how many documents per
-- batch — is a question about *ratios* ("this model holds together under N
-- tokens at this batch size; that one takes more"), and a ratio is a
-- measurement or it is a guess. This table is where the measurements live.
--
-- One row per (case, plane, protocol) attempt. `protocol`, `context_chars` and
-- `batch_size` are recorded from the first day even though only one protocol
-- exists yet: a measurement whose settings were not written down cannot be
-- compared with the next one, which is how benchmark tables become folklore.
--
-- Interface state, and emphatically so: a benchmark writes claims into a
-- *copy* of the store and throws it away (`app/bench.py`), so nothing here
-- has touched the knowledge at all.
CREATE TABLE IF NOT EXISTS bench_runs (
    bench_id      TEXT PRIMARY KEY,
    batch_id      TEXT NOT NULL DEFAULT '',   -- one press, many rows
    at            TEXT NOT NULL DEFAULT '',
    subject_id    TEXT NOT NULL DEFAULT '',
    subject       TEXT NOT NULL DEFAULT '',
    pack_id       TEXT NOT NULL DEFAULT '',
    plane         TEXT NOT NULL DEFAULT '',
    -- Which model or harness actually answered. The plane is the *how*; this
    -- is the *what*, and a ratio keyed by plane alone would average two
    -- different models into one meaningless number.
    model         TEXT NOT NULL DEFAULT '',
    protocol      TEXT NOT NULL DEFAULT '',
    context_chars INTEGER,
    batch_size    INTEGER,
    ms            INTEGER,
    -- NULL where nobody counted, never 0. The same distinction `research_runs`
    -- keeps: the harness plane costs the reader nothing beyond a subscription
    -- and still knows its tokens; a per-call price knows its dollars without
    -- ever seeing a token.
    tokens        INTEGER,
    usd           REAL,
    documents     INTEGER NOT NULL DEFAULT 0,
    findings      INTEGER NOT NULL DEFAULT 0,
    accepted      INTEGER NOT NULL DEFAULT 0,
    refused       INTEGER NOT NULL DEFAULT 0,
    -- The gate's own sentences, the top few. A plane that gathers plenty and
    -- loses it all at the grounding check is the interesting failure, and a
    -- count cannot show it.
    reasons_json  TEXT NOT NULL DEFAULT '[]',
    error         TEXT NOT NULL DEFAULT '',
    note          TEXT NOT NULL DEFAULT '',
    -- The ground-truth score, when the case carried any (B126): recall,
    -- precision and hallucination rate, with the entries behind each. JSON
    -- because it is read as a whole and never queried by field — and because
    -- a schema for it would be this table's third attempt at one.
    gold_json     TEXT NOT NULL DEFAULT '',
    -- Which repetition of the same (case, plane, protocol) this was. Language
    -- models are stochastic: a benchmark that runs once measures a sample and
    -- reports it as a constant.
    rep           INTEGER NOT NULL DEFAULT 1,
    -- `exa` | `tavily` | ''. B126 §8: which search provider fed this run its
    -- documents is a sweep axis, not a fact hidden inside `note` — the same
    -- model under the same protocol with two different searchers is two
    -- measurements, exactly as two protocols are. Added after the table
    -- existed, hence the empty default (see `add_missing_columns`).
    search_provider TEXT NOT NULL DEFAULT '',
    -- The case kind this row measured: specific | bulk | validation (B126
    -- §3). Each answers a different question and none of them should be
    -- averaged into the others without saying so.
    kind          TEXT NOT NULL DEFAULT 'specific'
);
CREATE INDEX IF NOT EXISTS bench_runs_at ON bench_runs (at DESC);

-- ── sites this installation knows how to read ────────────────────────────
--
-- An adapter says how to read one website: which selectors hold the fields,
-- what its labels mean. Packs ship them, which is right — an adapter is
-- knowledge about a site, and a pack is how knowledge travels.
--
-- But it left the reader with nothing to do on a site no pack covers, which is
-- every site except the one. "I cannot open the extension on pages that aren't
-- registered" is that, exactly: the panel is not missing, the *site* is, and
-- until now the only way to add one was to author a pack.
--
-- So a **local adapter**: one this installation learned, kept here rather than
-- in the store. That is not a convenience, it is the two-SQLite rule again — a
-- site the reader taught their own copy about is not pack content, must not
-- enter a `content_digest`, and must survive the pack being updated or
-- uninstalled. `app/sites.py` merges them behind the engine's own lookup, so
-- a pack that later ships an adapter for the same host wins and the local one
-- becomes redundant rather than conflicting.
CREATE TABLE IF NOT EXISTS local_adapters (
    host       TEXT PRIMARY KEY,
    -- The adapter document, as JSON, in the same shape a pack ships.
    spec_json  TEXT NOT NULL DEFAULT '{}',
    -- agent | reader. Who wrote it, because "an agent proposed this" and "I
    -- wrote this myself" carry different weight when it reads a page wrong.
    source     TEXT NOT NULL DEFAULT 'agent',
    -- Which pack's identity keys it maps into. An adapter that maps to keys no
    -- installed pack declares produces a lookup that resolves to nothing.
    pack_id    TEXT NOT NULL DEFAULT '',
    enabled    INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT ''
);

-- Sites the reader opened that nothing here can read yet.
--
-- The demand signal, and the only honest input to "which site should Kriko
-- learn next": a list of hosts somebody actually stood on and pressed the
-- button. Not browsing history — one row per host, a count, and the last page
-- they were on when they asked, which is what an agent needs to write the
-- adapter.
CREATE TABLE IF NOT EXISTS site_requests (
    host       TEXT PRIMARY KEY,
    asks       INTEGER NOT NULL DEFAULT 0,
    sample_url TEXT NOT NULL DEFAULT '',
    title      TEXT NOT NULL DEFAULT '',
    -- open | working | done | refused. `done` when an adapter exists for it.
    state      TEXT NOT NULL DEFAULT 'open',
    detail     TEXT NOT NULL DEFAULT '',
    first_at   TEXT NOT NULL DEFAULT '',
    last_at    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS site_requests_last ON site_requests (last_at DESC);

-- What the *browser* made of the sites this installation can read.
--
-- The app can see that an adapter exists; only the extension can see whether
-- Chrome ever granted the host permission that turns one into an injected
-- content script. Until this table existed the Sites screen showed "readable"
-- for a site the panel would never appear on, and the reader — correctly —
-- read that as the whole feature being broken. Reported by the extension after
-- each of its syncs, so a row is a fact about a browser and not a guess.
CREATE TABLE IF NOT EXISTS site_activation (
  host    TEXT PRIMARY KEY,
  state   TEXT NOT NULL DEFAULT '',   -- active|pending|refused
  detail  TEXT NOT NULL DEFAULT '',
  pattern TEXT NOT NULL DEFAULT '',
  at      TEXT NOT NULL DEFAULT ''
);
"""



#: The most operations one installation keeps. A feed, not an archive: the
#: durable record of what research *produced* is `submissions`, `pipeline_runs`
#: and `research_runs`, all of which outlive this. Rows here answer "what is
#: happening" and "what just happened", and both questions have a short reach.
OPERATIONS_KEPT = 2000


#: The most documents one installation keeps, newest first. A bound rather
#: than a sweep by age: what makes this table safe is that it cannot grow
#: without limit, and "the last N pages I accepted evidence from" is the set a
#: re-check actually reaches for. Roughly 10 MB at the sizes an agent submits.
DOCUMENTS_KEPT = 5000

#: And the most one document may be. Past this the row records that the source
#: was fetched and says the text is not kept — see the column comment.
MAX_DOCUMENT_CHARS = 200_000


#: The verdicts a reader may leave. Closed, and allowed to be a constant for
#: the reason CLAUDE.md's scalability rule carves out: this does not grow with
#: pack coverage. It is three answers to "was this any use", and a fourth
#: category would be a product decision, not a new car.
#:
#: `not_applicable` is separate from `wrong` because they mean opposite things
#: to whoever reads the marks later: "true of this engine but not of mine" is a
#: matching problem, "not true at all" is a knowledge problem, and collapsing
#: them would throw away the only signal that distinguishes the two.
VERDICTS = ("useful", "wrong", "not_applicable")

#: Long enough for any semver anyone will ship, short enough that a header is
#: not a place to put a payload.
MAX_VERSION_CHARS = 32


def connect(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # See kriko.store.db.connect: same reason, same failure. A request-scoped
    # connection is owned by the request, and FastAPI does not keep a request
    # on one worker thread.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    # Both of the lines below used to run unconditionally, which made every
    # read of the history a writer holding an exclusive lock. See
    # kriko.store.db._prepare for what that cost.
    if conn.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass  # another connection is doing it, or it is already done
    # Fingerprinted, not numbered — see kriko.store.db.schema_stamp. This
    # schema has already grown once (extension_seen, 0.3.1) and a hand-bumped
    # number is precisely the step that gets forgotten on the second one.
    stamp = schema_stamp(SCHEMA)
    if conn.execute("PRAGMA user_version").fetchone()[0] != stamp:
        conn.executescript(SCHEMA)
        # `CREATE TABLE IF NOT EXISTS` is a no-op on a table that already
        # exists, so a *column* added to SCHEMA above never appears in a
        # reader's file — the stamp moves, the script runs, and the column is
        # silently missing until the first query names it. New tables landed
        # fine, which is exactly why nobody noticed: the bug is invisible
        # until the first schema change of the other kind.
        add_missing_columns(conn)
        conn.execute(f"PRAGMA user_version = {stamp}")
        conn.commit()
    return conn


def declared_columns(sql: str = SCHEMA) -> dict[str, dict[str, str]]:
    """What SCHEMA says each table holds — parsed, never hand-listed.

    A migration list someone has to remember to extend is the step that gets
    forgotten (CLAUDE.md's scalability rule, applied to the schema rather than
    to the catalog). The declaration above is already the truth; this reads it.
    """
    tables: dict[str, dict[str, str]] = {}
    pattern = re.compile(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s*\((.*?)\n\);",
        re.DOTALL | re.IGNORECASE,
    )
    for name, body in pattern.findall(sql):
        columns: dict[str, str] = {}
        for part in _split_top_level(body):
            # A table constraint is not a column, and `PRIMARY KEY (a, b)`
            # would otherwise be read as a column called "PRIMARY".
            if part.split(None, 1)[0].upper() in _NOT_A_COLUMN:
                continue
            columns[part.split(None, 1)[0]] = part
        tables[name] = columns
    return tables


#: Leading words that begin a table constraint rather than a column.
_NOT_A_COLUMN = {"PRIMARY", "UNIQUE", "CHECK", "FOREIGN", "CONSTRAINT"}


def _split_top_level(body: str) -> list[str]:
    """Split a CREATE TABLE body on its own commas, comments removed.

    Depth-aware because `PRIMARY KEY (adapter_id, label)` and
    `DEFAULT (datetime('now'))` both carry commas that are not separators.
    """
    lines = [line.split("--", 1)[0] for line in body.splitlines()]
    text = "\n".join(lines)
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def add_missing_columns(conn: sqlite3.Connection, sql: str = SCHEMA) -> list[str]:
    """Bring an existing table up to what SCHEMA declares.

    Only additions, and only ones SQLite can add in place — which is the
    honest limit of a local file we must never rewrite behind the reader's
    back. This is *their* history and settings, not a cache: dropping the
    table to recreate it would trade a missing column for lost data, so a
    column SQLite refuses raises rather than being papered over. Anything
    beyond an added column is a real migration and has to be written as one.
    """
    added: list[str] = []
    for table, columns in declared_columns(sql).items():
        try:
            existing = {
                row[1] for row in conn.execute(f"PRAGMA table_info({table})")
            }
        except sqlite3.Error:
            continue
        if not existing:
            continue  # the CREATE above made it, or it is not ours
        for name, definition in columns.items():
            if name in existing:
                continue
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")
            added.append(f"{table}.{name}")
    if added:
        conn.commit()
    return added


def record_lookup(
    conn: sqlite3.Connection,
    *,
    source: str,
    label: str,
    request: dict,
    response: dict,
) -> str:
    lookup_id = secrets.token_hex(8)
    conn.execute(
        "INSERT INTO lookups"
        " (lookup_id, created_at, source, label, request_json, response_json)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            lookup_id,
            datetime.now(UTC).isoformat(timespec="seconds"),
            source,
            label,
            json.dumps(request, default=str),
            json.dumps(response, default=str),
        ),
    )
    conn.commit()
    return lookup_id


def _decode(row: sqlite3.Row) -> dict:
    return {
        "lookup_id": row["lookup_id"],
        "created_at": row["created_at"],
        "source": row["source"],
        "label": row["label"],
        "request": json.loads(row["request_json"]),
        "response": json.loads(row["response_json"]),
    }


def recent(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """Newest first.

    `created_at` has second resolution, so two lookups a moment apart tie on
    it; `rowid DESC` breaks the tie by insertion order rather than leaving it
    to SQLite. `claim_count` is computed here so a list view does not have to
    parse every stored response just to show a number.
    """
    rows = conn.execute(
        "SELECT lookup_id, created_at, source, label, response_json FROM lookups"
        " ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (max(0, limit),),
    ).fetchall()
    out = []
    for row in rows:
        response = json.loads(row["response_json"])
        out.append(
            {
                "lookup_id": row["lookup_id"],
                "created_at": row["created_at"],
                "source": row["source"],
                "label": row["label"],
                "claim_count": len(response.get("claims") or []),
            }
        )
    return out


def get_lookup(conn: sqlite3.Connection, lookup_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM lookups WHERE lookup_id = ?", (lookup_id,)
    ).fetchone()
    return _decode(row) if row else None


def delete_lookup(conn: sqlite3.Connection, lookup_id: str) -> bool:
    cursor = conn.execute("DELETE FROM lookups WHERE lookup_id = ?", (lookup_id,))
    # Forgetting an answer forgets the triage on it too. Leaving the checks
    # behind would let a new lookup that happened to reuse the id inherit
    # someone else's checkmarks.
    conn.execute("DELETE FROM claim_checks WHERE lookup_id = ?", (lookup_id,))
    conn.execute("DELETE FROM claim_notes WHERE lookup_id = ?", (lookup_id,))
    conn.commit()
    return cursor.rowcount > 0


# ── interface settings ───────────────────────────────────────────────────
#
# Deliberately a key/value table with JSON values rather than typed columns.
# Every row here is a UI preference — mode, a remembered pack — and none of
# them is worth a migration when the UI grows a fourth one.


def all_settings(conn: sqlite3.Connection) -> dict:
    return {
        row["key"]: json.loads(row["value"])
        for row in conn.execute("SELECT key, value FROM settings")
    }


def put_settings(conn: sqlite3.Connection, values: dict) -> dict:
    """Merge, never replace: a caller saving one preference must not clear
    the others just because it did not know about them."""
    conn.executemany(
        "INSERT INTO settings (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        [(key, json.dumps(value)) for key, value in values.items()],
    )
    conn.commit()
    return all_settings(conn)


# ── the browser extension ────────────────────────────────────────────────


def record_extension(
    conn: sqlite3.Connection, origin: str, version: str = ""
) -> None:
    """Note that an extension origin reached us just now, and what it is.

    Deliberately cheap and deliberately silent. It runs inside a middleware on
    a request the extension is waiting on, so it must not raise: a locked
    database or a schema older than this table would otherwise turn "the
    reader installed the extension" into "the extension reports the app is
    broken", which is precisely backwards.
    """
    now = _now()
    # Truncated rather than validated: this is a header, so it is whatever the
    # caller sent. It is only ever displayed and compared, never executed, and
    # a version string that is not a version reads as an extension that cannot
    # say what it is — which is the same conclusion by a different route.
    version = str(version or "")[:MAX_VERSION_CHARS]
    try:
        conn.execute(
            "INSERT INTO extension_seen (origin, first_at, last_at, hits, version)"
            " VALUES (?, ?, ?, 1, ?)"
            " ON CONFLICT(origin) DO UPDATE SET last_at = excluded.last_at,"
            " hits = extension_seen.hits + 1,"
            # COALESCE, not a plain overwrite: a request that carried no
            # header must not erase what an earlier one told us. Only a
            # non-blank version moves it.
            " version = CASE WHEN excluded.version = '' THEN extension_seen.version"
            "                ELSE excluded.version END",
            (origin, now, now, version),
        )
        conn.commit()
    except sqlite3.Error:
        pass


def extension_sightings(conn: sqlite3.Connection) -> list[dict]:
    """Every extension origin that has ever called, newest contact first."""
    return [
        dict(row)
        for row in conn.execute(
            "SELECT origin, first_at, last_at, hits, version FROM extension_seen"
            " ORDER BY last_at DESC"
        )
    ]


# ── triage ───────────────────────────────────────────────────────────────


def checked_keys(conn: sqlite3.Connection, lookup_id: str) -> list[str]:
    return [
        row["claim_key"]
        for row in conn.execute(
            "SELECT claim_key FROM claim_checks WHERE lookup_id = ?"
            " ORDER BY claim_key",
            (lookup_id,),
        )
    ]


def set_checked(
    conn: sqlite3.Connection, lookup_id: str, claim_key: str, checked: bool
) -> list[str]:
    if checked:
        conn.execute(
            "INSERT OR IGNORE INTO claim_checks (lookup_id, claim_key, created_at)"
            " VALUES (?, ?, ?)",
            (lookup_id, claim_key, datetime.now(UTC).isoformat(timespec="seconds")),
        )
    else:
        conn.execute(
            "DELETE FROM claim_checks WHERE lookup_id = ? AND claim_key = ?",
            (lookup_id, claim_key),
        )
    conn.commit()
    return checked_keys(conn, lookup_id)


def notes(conn: sqlite3.Connection, lookup_id: str) -> dict[str, str]:
    """Every note on one answer, keyed the way the UI keys a claim."""
    return {
        row["claim_key"]: row["note"]
        for row in conn.execute(
            "SELECT claim_key, note FROM claim_notes WHERE lookup_id = ?",
            (lookup_id,),
        )
    }


def set_note(
    conn: sqlite3.Connection, lookup_id: str, claim_key: str, note: str
) -> dict[str, str]:
    """Write one note, or clear it.

    An empty note deletes the row rather than storing `''`. A reader who
    selects their own text and deletes it has said "there is no note here",
    and an empty string would keep the claim in every "what did the seller
    say" list forever.
    """
    if note.strip():
        conn.execute(
            "INSERT INTO claim_notes (lookup_id, claim_key, note, updated_at)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT (lookup_id, claim_key) DO UPDATE SET"
            "   note = excluded.note, updated_at = excluded.updated_at",
            (lookup_id, claim_key, note.strip(), _now()),
        )
    else:
        conn.execute(
            "DELETE FROM claim_notes WHERE lookup_id = ? AND claim_key = ?",
            (lookup_id, claim_key),
        )
    conn.commit()
    return notes(conn, lookup_id)


# ── marks — what the reader thought of a claim ────────────────────────────


def mark_claim(
    conn: sqlite3.Connection,
    *,
    pack_id: str,
    claim_id: str,
    verdict: str,
    note: str = "",
    subject_id: str = "",
    title: str = "",
) -> dict:
    """Record or replace one verdict. Raises `ValueError` on an unknown one.

    Upsert rather than insert: a reader who marks a claim twice has changed
    their mind, and a history of one person's changing mind about one claim is
    not worth a table. `created_at` survives the change, so "when did I first
    flag this" is still answerable.
    """
    if verdict not in VERDICTS:
        raise ValueError(f"unknown verdict {verdict!r} (expected one of {VERDICTS})")
    now = datetime.now(UTC).isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO claim_marks"
        " (pack_id, claim_id, verdict, note, subject_id, title,"
        "  created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT (pack_id, claim_id) DO UPDATE SET"
        "   verdict = excluded.verdict, note = excluded.note,"
        "   subject_id = excluded.subject_id, title = excluded.title,"
        "   updated_at = excluded.updated_at",
        (pack_id, claim_id, verdict, note, subject_id, title, now, now),
    )
    conn.commit()
    return get_mark(conn, pack_id, claim_id) or {}


def get_mark(conn: sqlite3.Connection, pack_id: str, claim_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM claim_marks WHERE pack_id = ? AND claim_id = ?",
        (pack_id, claim_id),
    ).fetchone()
    return dict(row) if row else None


def unmark_claim(conn: sqlite3.Connection, pack_id: str, claim_id: str) -> bool:
    """Undo a mark. Pressing the same button again is how a reader takes it
    back, so this is a normal path rather than an administrative one."""
    changed = conn.execute(
        "DELETE FROM claim_marks WHERE pack_id = ? AND claim_id = ?",
        (pack_id, claim_id),
    ).rowcount
    conn.commit()
    return bool(changed)


def marks(
    conn: sqlite3.Connection, *, verdict: str | None = None, limit: int = 200
) -> list[dict]:
    """Every mark, newest change first."""
    sql = "SELECT * FROM claim_marks"
    params: list = []
    if verdict:
        sql += " WHERE verdict = ?"
        params.append(verdict)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(limit)
    return [dict(row) for row in conn.execute(sql, params)]


def mark_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """How many of each verdict, with the zeroes present.

    Every verdict is a key even at zero: a dashboard that renders only the
    non-empty ones changes shape as data arrives, and "no claims marked wrong"
    is a thing worth stating rather than omitting.
    """
    counts = {verdict: 0 for verdict in VERDICTS}
    for row in conn.execute(
        "SELECT verdict, COUNT(*) AS n FROM claim_marks GROUP BY verdict"
    ):
        counts[row["verdict"]] = row["n"]
    return counts


def mark_signals(conn: sqlite3.Connection, limit: int = 50) -> dict:
    """The two queues a mark feeds, derived rather than curated.

    A mark was a dead end: readers were answering "was this any use?" and the
    answer went into a table nothing read. This is the mechanism that reads it,
    and it is deliberately two queues rather than one list, because `wrong` and
    `not_applicable` are failures of different systems:

    * `research` — subjects carrying `wrong` marks. A knowledge problem: the
      claim is not true of the thing it was written for, so the fix is another
      research pass on that subject, which is a job this app already runs.
    * `matching` — subjects carrying `not_applicable` marks. A *matching*
      problem: the claim may be perfectly true of the product it was written
      for and this was not that one, so the fix is upstream of the claim —
      identity extraction, or a fitment gate that is too broad. `sources`
      attributes it: a subject the reader only ever reached from a listing URL
      points at the adapter, while one reached from the form points at the
      reader's own typing or at the gate.

    Both are counts and identifiers, never a review queue for a person: the
    automation principle says nothing in the data path waits on sign-off. What
    a human does with this is press "research", which is the same job an
    automated pass calls.

    `sources` is computed by asking the reader's own history which doors a
    subject arrived through. A scan, because history is local and small — and
    because the alternative is denormalising the door onto every mark, which
    would make a mark's meaning depend on when it was written.
    """
    doors: dict[str, dict[str, int]] = {}
    for row in conn.execute("SELECT source, response_json FROM lookups"):
        payload = json.loads(row["response_json"] or "{}")
        seen = {
            str(claim.get("subject_id") or "")
            for claim in payload.get("claims") or []
        }
        # `subjects` as well as the claims, and both shapes of it: /api/analyze
        # sends resolved rows and /api/lookup sends bare ids. A subject that
        # resolved and had nothing to say is exactly the interesting case here
        # — there is no claim to carry it, and it is still a match the adapter
        # made.
        for entry in payload.get("subjects") or []:
            seen.add(str(entry.get("subject_id") or "") if isinstance(entry, dict) else str(entry))
        for subject in seen - {""}:
            tally = doors.setdefault(subject, {})
            tally[row["source"]] = tally.get(row["source"], 0) + 1

    def queue(verdict: str, *, with_sources: bool) -> list[dict]:
        grouped: dict[tuple[str, str], dict] = {}
        for mark in marks(conn, verdict=verdict, limit=1000):
            key = (mark["subject_id"], mark["pack_id"])
            item = grouped.setdefault(
                key,
                {
                    "subject_id": mark["subject_id"],
                    "pack_id": mark["pack_id"],
                    "count": 0,
                    # The reader's own words are the most valuable field on a
                    # mark, so they travel with the queue rather than being
                    # aggregated away.
                    "notes": [],
                    "claim_ids": [],
                },
            )
            item["count"] += 1
            item["claim_ids"].append(mark["claim_id"])
            if mark["note"]:
                item["notes"].append(mark["note"])
        out = sorted(
            grouped.values(), key=lambda item: (-item["count"], item["subject_id"])
        )
        if with_sources:
            for item in out:
                item["sources"] = doors.get(item["subject_id"], {})
        return out[:limit]

    return {
        "research": queue("wrong", with_sources=False),
        "matching": queue("not_applicable", with_sources=True),
    }


# ── submissions ─ what a researcher sent, and what survived ────────


#: How a submission reached the acceptance path. Two doors, and the constant
#: exists so a third one cannot be added without naming itself here.
DOORS = ("mcp", "job")


def record_submission(
    conn: sqlite3.Connection,
    *,
    door: str,
    subject_id: str,
    pack_id: str,
    verdicts: dict,
    queries: Sequence[str] | None = None,
) -> str:
    """Store one batch's outcome. Returns the row id.

    The whole verdict payload is kept as JSON rather than split into rows per
    finding: what an author reads is "this batch, these refusals, in the gate's
    own sentences", and the reasons are free text from `kriko.gates` that no
    schema here should try to enumerate.
    """
    accepted = verdicts.get("accepted") or []
    refused = verdicts.get("rejected") or []
    submission_id = secrets.token_hex(8)
    conn.execute(
        "INSERT INTO submissions (submission_id, created_at, door, subject_id,"
        " pack_id, accepted, refused, verdicts_json, queries_json)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (
            submission_id,
            _now(),
            door if door in DOORS else "job",
            subject_id,
            pack_id,
            len(accepted),
            len(refused),
            json.dumps(verdicts, default=str),
            json.dumps([str(query) for query in (queries or ())]),
        ),
    )
    conn.commit()
    return submission_id


def retain_documents(conn: sqlite3.Connection, documents: Sequence[dict]) -> int:
    """Keep the text each accepted quote was proved against. Returns rows kept.

    Called from `app.findings.log_submission`, which is the one place both
    doors already meet — so a document is kept on the same terms whether the
    finding arrived through MCP or through an in-app job, and acceptance
    itself still never touches this file (see that function's docstring for
    why the two connections stay apart).

    Replaces rather than ignores: a second submission quoting the same page is
    the more recent read of it, and a stale copy is the one thing worth less
    than no copy.
    """
    kept = 0
    for one in documents or ():
        source_id = str(one.get("source_id") or "").strip()
        if not source_id:
            continue
        text = str(one.get("text") or "")
        conn.execute(
            "INSERT OR REPLACE INTO documents (source_id, pack_id, url, text,"
            " chars, retained_at) VALUES (?,?,?,?,?,?)",
            (
                source_id,
                str(one.get("pack_id") or ""),
                str(one.get("url") or ""),
                text if len(text) <= MAX_DOCUMENT_CHARS else "",
                len(text),
                _now(),
            ),
        )
        kept += 1
    if kept:
        # Pruned here rather than on a timer: this is the only writer, so it
        # is the only moment the bound can be exceeded.
        conn.execute(
            "DELETE FROM documents WHERE source_id NOT IN ("
            " SELECT source_id FROM documents"
            " ORDER BY retained_at DESC, source_id DESC LIMIT ?)",
            (DOCUMENTS_KEPT,),
        )
        conn.commit()
    return kept


def local_adapters(conn: sqlite3.Connection, *, enabled_only: bool = True) -> list[dict]:
    sql = "SELECT * FROM local_adapters"
    if enabled_only:
        sql += " WHERE enabled = 1"
    out = []
    for row in conn.execute(sql + " ORDER BY host").fetchall():
        one = dict(row)
        try:
            one["spec"] = json.loads(one.pop("spec_json") or "{}")
        except ValueError:
            one["spec"] = {}
        out.append(one)
    return out


def save_local_adapter(
    conn: sqlite3.Connection,
    *,
    host: str,
    spec: dict,
    source: str = "agent",
    pack_id: str = "",
) -> dict:
    now = _now()
    conn.execute(
        "INSERT INTO local_adapters (host, spec_json, source, pack_id, enabled,"
        " created_at, updated_at) VALUES (?,?,?,?,1,?,?)"
        " ON CONFLICT (host) DO UPDATE SET spec_json = excluded.spec_json,"
        " source = excluded.source, pack_id = excluded.pack_id,"
        " enabled = 1, updated_at = excluded.updated_at",
        (host, json.dumps(spec), source, pack_id, now, now),
    )
    conn.commit()
    return {"host": host, "source": source, "pack_id": pack_id}


def forget_local_adapter(conn: sqlite3.Connection, host: str) -> bool:
    done = conn.execute("DELETE FROM local_adapters WHERE host = ?", (host,))
    conn.commit()
    return bool(done.rowcount)


def record_site_request(
    conn: sqlite3.Connection, *, host: str, url: str = "", title: str = ""
) -> dict:
    """One more ask for a site nothing can read yet. Accumulated, not appended.

    A count and a sample, because the question it answers is "which site should
    Kriko learn next" and that is about distinct hosts, not about how much
    somebody browsed.
    """
    now = _now()
    conn.execute(
        "INSERT INTO site_requests (host, asks, sample_url, title, first_at, last_at)"
        " VALUES (?,1,?,?,?,?)"
        " ON CONFLICT (host) DO UPDATE SET asks = asks + 1,"
        " sample_url = CASE WHEN excluded.sample_url <> '' THEN excluded.sample_url"
        "                   ELSE site_requests.sample_url END,"
        " title = CASE WHEN excluded.title <> '' THEN excluded.title"
        "              ELSE site_requests.title END,"
        " last_at = excluded.last_at",
        (host, url, title, now, now),
    )
    conn.commit()
    return site_requests(conn, host=host)[0]


def set_site_request(conn: sqlite3.Connection, host: str, *, state: str,
                     detail: str = "") -> None:
    conn.execute(
        "UPDATE site_requests SET state = ?, detail = ?, last_at = ?"
        " WHERE host = ?",
        (state, detail, _now(), host),
    )
    conn.commit()


def forget_site_request(conn: sqlite3.Connection, host: str) -> bool:
    """Drop an ask. Called when the site became readable — it is not an ask any more."""
    done = conn.execute("DELETE FROM site_requests WHERE host = ?", (host,))
    conn.commit()
    return bool(done.rowcount)


def record_activation(conn: sqlite3.Connection, rows) -> int:
    """What the extension's last sync made of each site. Replaces, never merges.

    A whole-list replace because the extension's status *is* the whole list:
    a site it no longer reports is one it no longer has registered, and
    merging would leave the screen claiming an activation that no browser
    still holds.
    """
    now = _now()
    conn.execute("DELETE FROM site_activation")
    for row in rows:
        host = str(row.get("site") or "").strip().lower()
        if not host:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO site_activation (host, state, detail,"
            " pattern, at) VALUES (?,?,?,?,?)",
            (host, str(row.get("state") or "")[:32],
             str(row.get("detail") or "")[:500],
             str(row.get("pattern") or "")[:200], now),
        )
    conn.commit()
    return len(rows)


def activations(conn: sqlite3.Connection) -> dict[str, dict]:
    return {
        row["host"]: dict(row)
        for row in conn.execute("SELECT * FROM site_activation")
    }


def site_requests(conn: sqlite3.Connection, *, host: str = "") -> list[dict]:
    sql = "SELECT * FROM site_requests"
    args: list = []
    if host:
        sql += " WHERE host = ?"
        args.append(host)
    sql += " ORDER BY asks DESC, last_at DESC"
    return [dict(row) for row in conn.execute(sql, args).fetchall()]


def record_bench(conn: sqlite3.Connection, row: dict) -> str:
    """One measured attempt. Returns its id."""
    bench_id = secrets.token_hex(8)
    conn.execute(
        "INSERT INTO bench_runs (bench_id, batch_id, at, subject_id, subject,"
        " pack_id, plane, model, protocol, context_chars, batch_size, ms,"
        " tokens, usd, documents, findings, accepted, refused, reasons_json,"
        " error, note, gold_json, rep, search_provider, kind)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            bench_id,
            str(row.get("batch_id") or ""),
            _now(),
            str(row.get("subject_id") or ""),
            str(row.get("subject") or ""),
            str(row.get("pack_id") or ""),
            str(row.get("plane") or ""),
            str(row.get("model") or ""),
            str(row.get("protocol") or ""),
            row.get("context_chars"),
            row.get("batch_size"),
            row.get("ms"),
            row.get("tokens"),
            row.get("usd"),
            int(row.get("documents") or 0),
            int(row.get("findings") or 0),
            int(row.get("accepted") or 0),
            int(row.get("refused") or 0),
            json.dumps(list(row.get("reasons") or [])),
            str(row.get("error") or "")[:2000],
            str(row.get("note") or "")[:2000],
            json.dumps(row.get("gold")) if row.get("gold") else "",
            int(row.get("rep") or 1),
            str(row.get("search_provider") or ""),
            str(row.get("kind") or "specific"),
        ),
    )
    conn.commit()
    return bench_id


def bench_runs(conn: sqlite3.Connection, *, limit: int = 100) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM bench_runs ORDER BY at DESC, rowid DESC LIMIT ?",
        (max(1, min(limit, 1000)),),
    ).fetchall()
    out = []
    for row in rows:
        one = dict(row)
        try:
            one["reasons"] = json.loads(one.pop("reasons_json") or "[]")
        except ValueError:
            one["reasons"] = []
        try:
            one["gold"] = json.loads(one.pop("gold_json") or "null")
        except ValueError:
            one["gold"] = None
        out.append(one)
    return out


def bench_summary(conn: sqlite3.Connection) -> list[dict]:
    """Per (plane, model, protocol): what it costs and what survives.

    The acceptance *rate* rather than a count, because that is the number the
    comparison turns on — a plane that returns thirty findings and keeps two
    is worse than one that returns four and keeps three, and only the rate says
    so. Grouped by protocol as well as by model, since that is the whole point
    of B123: the same model under two protocols is two measurements.
    """
    rows = conn.execute(
        "SELECT plane, model, protocol, COUNT(*) AS runs,"
        " AVG(ms) AS ms, SUM(tokens) AS tokens, SUM(usd) AS usd,"
        " SUM(documents) AS documents, SUM(findings) AS findings,"
        " SUM(accepted) AS accepted, SUM(refused) AS refused,"
        " SUM(CASE WHEN error <> '' THEN 1 ELSE 0 END) AS failures"
        " FROM bench_runs GROUP BY plane, model, protocol"
        " ORDER BY plane, model, protocol"
    ).fetchall()
    out = []
    for row in rows:
        one = dict(row)
        kept = (one["accepted"] or 0) + (one["refused"] or 0)
        one["acceptance"] = round((one["accepted"] or 0) / kept, 3) if kept else None
        out.append(one)
    return out


def open_operation(
    conn: sqlite3.Connection,
    *,
    door: str,
    kind: str,
    name: str,
    subject_id: str = "",
    pack_id: str = "",
    request: str = "",
) -> int:
    """Start an operation row. Returns its id.

    Opened *before* the work rather than written after it, because a call that
    is still running is the row a live feed most needs — and a call that never
    returns leaves a `running` row that says so, which is the one thing a
    write-on-completion log can never do.
    """
    cursor = conn.execute(
        "INSERT INTO operations (door, kind, name, subject_id, pack_id, state,"
        " request_json, started_at) VALUES (?,?,?,?,?,'running',?,?)",
        (door, kind, name, subject_id, pack_id, request, _now()),
    )
    conn.commit()
    assert cursor.lastrowid is not None
    return cursor.lastrowid


def close_operation(
    conn: sqlite3.Connection,
    op_id: int,
    *,
    state: str = "ok",
    response: str = "",
    error: str = "",
    ms: int | None = None,
    usd: float | None = None,
    tokens: int | None = None,
) -> None:
    """Close an operation row. `usd`/`tokens` are `None` unless a caller
    actually counted one (B118) — see the column's own note on why that must
    never be papered over as a measured zero."""
    conn.execute(
        "UPDATE operations SET state = ?, response_json = ?, error = ?,"
        " ms = ?, ended_at = ?, usd = ?, tokens = ? WHERE op_id = ?",
        (state, response, error, ms, _now(), usd, tokens, op_id),
    )
    conn.execute(
        "DELETE FROM operations WHERE op_id NOT IN ("
        " SELECT op_id FROM operations ORDER BY op_id DESC LIMIT ?)",
        (OPERATIONS_KEPT,),
    )
    conn.commit()


def operations(
    conn: sqlite3.Connection, *, limit: int = 50, after_id: int = 0
) -> list[dict]:
    """The newest operations, or everything since `after_id`.

    Two shapes from one function because a feed needs both: a page on open,
    then the tail on every poll. `after_id` returns *ascending* ids so a
    consumer can append and remember the last one.
    """
    if after_id:
        rows = conn.execute(
            "SELECT * FROM operations WHERE op_id > ? ORDER BY op_id LIMIT ?",
            (after_id, max(1, min(limit, 500))),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM operations ORDER BY op_id DESC LIMIT ?",
            (max(1, min(limit, 500)),),
        ).fetchall()
    return [dict(row) for row in rows]


def running_operations(conn: sqlite3.Connection) -> int:
    """How many are open right now. The feed's one summary number."""
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM operations WHERE state = 'running'"
    ).fetchone()
    return int(row["n"])


def interrupt_running_operations(conn: sqlite3.Connection) -> int:
    """At startup, an operation still `running` belongs to a dead process.

    The same rule the jobs table follows, for the same reason: a row that spins
    forever after a restart is worse than no row, because it is the one thing a
    reader cannot tell from work in progress.
    """
    done = conn.execute(
        "UPDATE operations SET state = 'failed', error = 'interrupted',"
        " ended_at = ? WHERE state = 'running'",
        (_now(),),
    )
    conn.commit()
    return done.rowcount or 0


def document_for(conn: sqlite3.Connection, source_id: str) -> dict | None:
    """The kept page for one source, or `None` if this install never saw it.

    `None` is the answer B112 needs: a `source_url` no run ever fetched is a
    fabrication with a plausible shape, and until this table nothing could
    tell the two apart.
    """
    row = conn.execute(
        "SELECT source_id, pack_id, url, text, chars, retained_at"
        " FROM documents WHERE source_id = ?",
        (source_id,),
    ).fetchone()
    return dict(row) if row is not None else None


def documents_kept(conn: sqlite3.Connection) -> dict:
    """How much of the evidence is re-checkable offline. For the status view."""
    row = conn.execute(
        "SELECT COUNT(*) AS rows, COALESCE(SUM(LENGTH(text)), 0) AS chars"
        " FROM documents"
    ).fetchone()
    return {"documents": row["rows"], "chars": row["chars"]}


def _submission(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["verdicts"] = json.loads(out.pop("verdicts_json") or "{}")
    out["queries"] = json.loads(out.pop("queries_json", None) or "[]")
    return out


def submissions(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    """Newest batch first."""
    return [
        _submission(row)
        for row in conn.execute(
            "SELECT * FROM submissions ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (max(0, limit),),
        )
    ]


def refusal_reasons(conn: sqlite3.Connection, limit: int = 400) -> list[dict]:
    """Why findings are being refused, commonest first.

    Computed here rather than stored as a column because the reasons are
    sentences, not codes: they are grouped on their first clause, which is the
    part `kriko.gates` writes and the part that names the rule. Everything
    after an em dash is advice to the agent about that one finding.
    """
    tally: dict[str, int] = {}
    for row in conn.execute(
        "SELECT verdicts_json FROM submissions"
        " ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (max(0, limit),),
    ):
        for item in json.loads(row["verdicts_json"] or "{}").get("rejected") or []:
            reason = str(item.get("reason") or "unstated")
            head = reason.split("—")[0].split(";")[0].strip() or reason
            tally[head] = tally.get(head, 0) + 1
    return [
        {"reason": reason, "count": count}
        for reason, count in sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def query_shapes(conn: sqlite3.Connection, limit: int = 400) -> list[dict]:
    """Which searches produced kept findings, best first.

    The pack's `research/templates.yaml` is a set of *seeds* an agent adapts
    per subject and market, so the question an author actually has is not "what
    did I write" but "what did searching that way get me". A batch's queries
    are credited with everything that batch kept and everything it lost, which
    is coarse — a run rarely ties one claim to one search — but it is the
    honest granularity of what the submission door can know, and it is enough
    to tell a shape that keeps nothing from one that keeps most of what it
    finds.
    """
    tally: dict[str, list[int]] = {}
    for row in conn.execute(
        "SELECT queries_json, accepted, refused FROM submissions"
        " ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (max(0, limit),),
    ):
        for query in json.loads(row["queries_json"] or "[]"):
            seen = tally.setdefault(str(query), [0, 0, 0])
            seen[0] += 1
            seen[1] += int(row["accepted"] or 0)
            seen[2] += int(row["refused"] or 0)
    return [
        {"query": query, "batches": runs, "accepted": kept, "refused": lost}
        for query, (runs, kept, lost) in sorted(
            tally.items(), key=lambda kv: (-kv[1][1], -kv[1][0], kv[0])
        )
    ]


# ── jobs ─────────────────────────────────────────────────────────────────
#
# `queued -> running -> (succeeded | failed | cancelled | interrupted)`.
# `interrupted` is not an error state a handler can produce: it is what a row
# left `running` by a killed process becomes at the next startup, so a lost job
# is visible as a state rather than as a spinner nobody can explain.

QUEUED, RUNNING = "queued", "running"
#: Asked to stop, still tearing down. A real state rather than a message,
#: because the reader pressed a button and the two honest answers — "stopping"
#: and "stopped" — were rendered identically while in-flight work drained. A
#: run that says `cancelled` while it is still spending is the complaint;
#: one that still says `running` after the reader stopped it is the same
#: complaint wearing the other hat.
CANCELLING = "cancelling"
SUCCEEDED, FAILED, CANCELLED, INTERRUPTED = (
    "succeeded",
    "failed",
    "cancelled",
    "interrupted",
)
TERMINAL = frozenset({SUCCEEDED, FAILED, CANCELLED, INTERRUPTED})
#: States a job is still alive in. `CANCELLING` is here, not in TERMINAL: the
#: worker has not finished, and a poller that stopped watching would miss the
#: partial being written.
LIVE = frozenset({QUEUED, RUNNING, CANCELLING})


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def create_job(conn: sqlite3.Connection, kind: str, params: dict) -> str:
    job_id = secrets.token_hex(8)
    conn.execute(
        "INSERT INTO jobs (job_id, kind, params_json, state, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (job_id, kind, json.dumps(params, default=str), QUEUED, _now()),
    )
    conn.commit()
    return job_id


def start_job(conn: sqlite3.Connection, job_id: str) -> None:
    conn.execute(
        "UPDATE jobs SET state = ?, started_at = ? WHERE job_id = ?",
        (RUNNING, _now(), job_id),
    )
    conn.commit()


def update_job(
    conn: sqlite3.Connection,
    job_id: str,
    *,
    progress: float | None = None,
    message: str | None = None,
    line: str | None = None,
) -> None:
    """Progress, a headline, and an appended log line — any subset.

    The log is appended in SQL rather than read-modify-written in Python so a
    reader polling the row cannot see a line vanish between two writes.
    """
    sets: list[str] = []
    args: list[float | str | int] = []
    if progress is not None:
        sets.append("progress = ?")
        args.append(max(0.0, min(1.0, progress)))
    if message is not None:
        sets.append("message = ?")
        args.append(message)
    if line is not None:
        sets.append("log = log || ?")
        args.append(f"{line}\n")
    if not sets:
        return
    args.append(job_id)
    conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE job_id = ?", args)
    conn.commit()


def finish_job(
    conn: sqlite3.Connection,
    job_id: str,
    state: str,
    *,
    result: dict | None = None,
    message: str = "",
) -> None:
    conn.execute(
        "UPDATE jobs SET state = ?, finished_at = ?, progress = ?,"
        "       message = COALESCE(NULLIF(?, ''), message), result_json = ?"
        " WHERE job_id = ?",
        (
            state,
            _now(),
            1.0 if state == SUCCEEDED else 0.0,
            message,
            json.dumps(result, default=str) if result is not None else None,
            job_id,
        ),
    )
    conn.commit()


def request_cancel(conn: sqlite3.Connection, job_id: str) -> str | None:
    """Ask a job to stop, and report the state it is in.

    A queued job is cancelled outright — nothing has happened yet. A running
    one is only *asked*: the flag is a row the handler reads between steps,
    because killing a thread mid-write is how a half-installed pack happens.
    """
    row = get_job(conn, job_id)
    if row is None:
        return None
    if row["state"] == QUEUED:
        finish_job(conn, job_id, CANCELLED, message="cancelled before it started")
        return CANCELLED
    if row["state"] in (RUNNING, CANCELLING):
        # Idempotent on purpose. A reader who presses a button that appears to
        # do nothing presses it again, and a second press must not queue a
        # second teardown or reset the clock on the first.
        #
        # The state guard is in the WHERE clause rather than in the `if` above,
        # because the worker is running while this executes: between reading
        # the row and writing it, the job can finish. Without it a second press
        # arriving in that window writes `cancelling` over `cancelled` and the
        # run is left looking alive forever — a spinner nobody can clear, which
        # is worse than the unresponsive button it was meant to fix.
        done = conn.execute(
            "UPDATE jobs SET cancel_requested = 1, state = ?, message = ?"
            " WHERE job_id = ? AND state IN (?, ?)",
            (CANCELLING, "stopping…", job_id, RUNNING, CANCELLING),
        )
        conn.commit()
        if not done.rowcount:
            return (get_job(conn, job_id) or {}).get("state") or CANCELLED
        return CANCELLING
    return row["state"]


def save_partial(conn: sqlite3.Connection, job_id: str, result: dict) -> None:
    """Keep what a running job has finished, before it is asked to stop.

    Written *as the work happens* rather than at the end, which is the whole
    point: the reader cancelled a run that had already gathered sources and
    extracted findings, and all of it went in the bin because the only place
    a result was ever written was the success path. Nothing that reached this
    row is lost by stopping.
    """
    conn.execute(
        "UPDATE jobs SET result_json = ? WHERE job_id = ?",
        (json.dumps(result, default=str), job_id),
    )
    conn.commit()


def partial_of(conn: sqlite3.Connection, job_id: str) -> dict:
    row = conn.execute(
        "SELECT result_json FROM jobs WHERE job_id = ?", (job_id,)
    ).fetchone()
    if row is None or not row["result_json"]:
        return {}
    try:
        found = json.loads(row["result_json"])
    except json.JSONDecodeError:
        return {}
    return found if isinstance(found, dict) else {}


def cancel_requested(conn: sqlite3.Connection, job_id: str) -> bool:
    row = conn.execute(
        "SELECT cancel_requested FROM jobs WHERE job_id = ?", (job_id,)
    ).fetchone()
    return bool(row and row["cancel_requested"])


def _job(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["params"] = json.loads(out.pop("params_json") or "{}")
    result = out.pop("result_json")
    out["result"] = json.loads(result) if result else None
    out["cancel_requested"] = bool(out["cancel_requested"])
    out["done"] = out["state"] in TERMINAL
    return out


def get_job(conn: sqlite3.Connection, job_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
    return _job(row) if row else None


def list_jobs(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM jobs ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (max(0, limit),),
    ).fetchall()
    return [_job(row) for row in rows]


def work_in_flight(conn: sqlite3.Connection) -> int:
    """How many jobs are queued or running right now.

    Exists for the scheduler (B98). The job runner has a single worker, so an
    unattended tick that submitted while something was already in flight would
    not run in parallel — it would *queue behind it*, and a timer that queues
    faster than the worker drains builds a backlog nobody asked for. The tick
    therefore asks first and skips.
    """
    return conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE state IN (?, ?)", (QUEUED, RUNNING)
    ).fetchone()[0]


def interrupt_running(conn: sqlite3.Connection) -> int:
    """Called at startup. Anything still `running` belongs to a dead process."""
    # `CANCELLING` belongs in here with the other two. Left out, a job whose
    # process died mid-teardown is the one row that spins forever after a
    # restart — exactly what this function exists to prevent.
    cursor = conn.execute(
        "UPDATE jobs SET state = ?, finished_at = ?, message = ?"
        " WHERE state IN (?, ?, ?)",
        (
            INTERRUPTED,
            _now(),
            "the server stopped while this was running",
            RUNNING,
            QUEUED,
            CANCELLING,
        ),
    )
    conn.commit()
    return cursor.rowcount


# ── labels no adapter reads ──────────────────────────────────────────────


#: How many distinct labels one lookup may contribute. A page whose markup
#: changed wholesale, or one an adapter matched by mistake, can carry
#: hundreds — and a hundred labels from one page is not a hundred signals, it
#: is one. Capping keeps a single odd page from burying the handful of
#: labels that actually recur.
MAX_UNMAPPED_PER_LOOKUP = 25

#: A label longer than this is not a label. It is a paragraph that ended up in
#: a definition list, and storing it whole makes the table unreadable.
MAX_LABEL_CHARS = 120


def record_unmapped(
    conn: sqlite3.Connection,
    adapter_id: str,
    labels,
    *,
    url: str = "",
) -> int:
    """Count the labels this page had that the adapter does not read.

    Idempotent per (adapter, label) and additive in `seen`, so the answer to
    "is this recurring or was it once" survives without a row per sighting.

    Best-effort by contract: every caller is on the path of a reader waiting
    for an answer, and a coverage signal is never worth the answer. The count
    of labels actually written is returned so a test can tell "nothing to
    record" from "recording failed".
    """
    if not adapter_id:
        return 0
    now = _now()
    written = 0
    for label in list(labels)[:MAX_UNMAPPED_PER_LOOKUP]:
        text = str(label).strip()[:MAX_LABEL_CHARS]
        if not text:
            continue
        conn.execute(
            """
            INSERT INTO unmapped_labels
                (adapter_id, label, seen, first_at, last_at, sample_url)
            VALUES (?, ?, 1, ?, ?, ?)
            ON CONFLICT(adapter_id, label) DO UPDATE SET
                seen = seen + 1,
                last_at = excluded.last_at,
                sample_url = excluded.sample_url
            """,
            (adapter_id, text, now, now, url),
        )
        written += 1
    conn.commit()
    return written


def unmapped_labels(
    conn: sqlite3.Connection, limit: int = 100, *, adapter_id: str = ""
) -> list[dict]:
    """The labels, most recently seen first.

    Recency before frequency on purpose: a label that appeared today is the
    one that might mean the site changed this week, and a label seen four
    hundred times over six months is a known gap somebody already decided not
    to map.
    """
    where, args = "", []
    if adapter_id:
        where, args = "WHERE adapter_id = ?", [adapter_id]
    rows = conn.execute(
        f"""
        SELECT adapter_id, label, seen, first_at, last_at, sample_url
          FROM unmapped_labels {where}
      ORDER BY last_at DESC, seen DESC
         LIMIT ?
        """,
        (*args, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def forget_unmapped(conn: sqlite3.Connection, adapter_id: str, label: str) -> bool:
    """Drop one label.

    The dismissal an author needs: "Takasa Uygun" is never going to be mapped
    and a list that cannot be pruned stops being read. Deleting a row that
    recurs is not permanent — the next listing carrying it puts it back with a
    fresh `first_at`, which is the correct answer to "I said I did not care
    and it is still happening".
    """
    cur = conn.execute(
        "DELETE FROM unmapped_labels WHERE adapter_id = ? AND label = ?",
        (adapter_id, label),
    )
    conn.commit()
    return cur.rowcount > 0


# ── fact checks — what the cited page says now ────────────────────────────


def record_fact_check(
    conn: sqlite3.Connection,
    *,
    pack_id: str,
    claim_id: str,
    verdict: str,
    detail: str = "",
    sources: list[dict] | None = None,
    subject_id: str = "",
    title: str = "",
) -> dict:
    """Store the result of one re-check, replacing any earlier one."""
    if verdict not in factcheck.VERDICTS:
        raise ValueError(f"unknown verdict {verdict!r}")
    now = datetime.now(UTC).isoformat(timespec="seconds")
    conn.execute(
        "INSERT INTO fact_checks"
        " (pack_id, claim_id, verdict, detail, sources_json, subject_id,"
        "  title, checked_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT (pack_id, claim_id) DO UPDATE SET"
        "   verdict = excluded.verdict, detail = excluded.detail,"
        "   sources_json = excluded.sources_json,"
        "   subject_id = excluded.subject_id, title = excluded.title,"
        "   checked_at = excluded.checked_at",
        (
            pack_id,
            claim_id,
            verdict,
            detail,
            json.dumps(sources or []),
            subject_id,
            title,
            now,
        ),
    )
    conn.commit()
    return get_fact_check(conn, pack_id, claim_id) or {}


def _fact_check(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["sources"] = json.loads(out.pop("sources_json") or "[]")
    return out


def get_fact_check(
    conn: sqlite3.Connection, pack_id: str, claim_id: str
) -> dict | None:
    row = conn.execute(
        "SELECT * FROM fact_checks WHERE pack_id = ? AND claim_id = ?",
        (pack_id, claim_id),
    ).fetchone()
    return _fact_check(row) if row else None


def fact_checks(
    conn: sqlite3.Connection, *, verdict: str | None = None, limit: int = 200
) -> list[dict]:
    """Every re-check, newest first — the queue a research pass wants.

    A `missing` verdict names a claim whose source has moved on, which is the
    highest-signal thing this app can hand an automated pass: the claim is not
    wrong, it is unsupported, and that is a re-research target rather than a
    deletion.
    """
    clause, args = "", []
    if verdict:
        clause, args = " WHERE verdict = ?", [verdict]
    return [
        _fact_check(row)
        for row in conn.execute(
            f"SELECT * FROM fact_checks{clause} ORDER BY checked_at DESC LIMIT ?",
            (*args, limit),
        )
    ]


def fact_check_counts(conn: sqlite3.Connection) -> dict:
    rows = conn.execute(
        "SELECT verdict, COUNT(*) AS n FROM fact_checks GROUP BY verdict"
    ).fetchall()
    return {row["verdict"]: row["n"] for row in rows}


# ── research provenance and undo ──────────────────────────────────────────


def open_research_run(
    conn: sqlite3.Connection,
    run_id: str,
    *,
    job_id: str = "",
    plane: str = "",
    model: str = "",
    search_provider: str = "",
    budget_usd: float | None = None,
) -> None:
    """Write the run down before it spends anything.

    Opened rather than recorded-on-completion for the reason the jobs table
    exists: a run that crashed or was killed mid-way is the one a reader most
    needs to be able to read afterwards, and a row written at the end is a row
    that is never written for exactly those runs.

    `spent_usd` opens NULL rather than 0.0. The agent plane never counts, so
    its rows stay NULL for their whole life, and "cost nothing" and "nobody
    counted" are different answers a cost column has to keep apart — opening
    at 0.0 makes every unmeasured run claim a measured zero, and `close`'s
    COALESCE then preserves the claim.
    """
    conn.execute(
        "INSERT OR REPLACE INTO research_runs"
        " (run_id, job_id, plane, model, search_provider, budget_usd,"
        "  spent_usd, started_at, outcome)"
        " VALUES (?, ?, ?, ?, ?, ?, NULL, ?, '')",
        (run_id, job_id or None, plane, model, search_provider, budget_usd, _now()),
    )
    conn.commit()


def close_research_run(
    conn: sqlite3.Connection,
    run_id: str,
    outcome: str,
    spent_usd: float | None = None,
    tokens_used: int | None = None,
) -> None:
    """What it cost, on the way out — both currencies, both optional.

    `COALESCE` on each, so a caller that knows one and not the other cannot
    erase the one already written. A plane that counts neither leaves both
    NULL for the row's whole life, which is the truthful record of a run
    nobody metered.
    """
    conn.execute(
        "UPDATE research_runs SET outcome = ?, spent_usd = COALESCE(?, spent_usd),"
        " tokens_used = COALESCE(?, tokens_used), ended_at = ? WHERE run_id = ?",
        (outcome, spent_usd, tokens_used, _now(), run_id),
    )
    conn.commit()


def record_run_claims(
    conn: sqlite3.Connection, run_id: str, pack_id: str, subject_id: str, accepted: list
) -> int:
    """Remember which claims this run put in, so they can be taken back out."""
    rows = [
        (run_id, pack_id, item["claim_id"], subject_id, item.get("title") or "")
        for item in accepted or []
        if item.get("claim_id")
    ]
    conn.executemany(
        "INSERT OR IGNORE INTO research_run_claims"
        " (run_id, pack_id, claim_id, subject_id, title) VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def _research_run(row: sqlite3.Row) -> dict:
    return {
        "run_id": row["run_id"],
        "job_id": row["job_id"] or "",
        "plane": row["plane"],
        # `llm` on the wire, `model` in the column. Not a whim: `model` is a
        # car identity key, and `test_ui_contains_no_pack_vocabulary` bans
        # every pack identity word from `ui/src` — correctly, because a
        # literal key name in the frontend is the scalability bug in a
        # language the AST test cannot read. The collision is real rather
        # than incidental (a car has a model; so does a completion API), so
        # the interface uses the word no pack can claim.
        "llm": row["model"],
        "search_provider": row["search_provider"],
        "budget_usd": row["budget_usd"],
        "spent_usd": row["spent_usd"],
        "tokens_used": row["tokens_used"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"] or "",
        "outcome": row["outcome"],
        "claims": row["claims"] if "claims" in row.keys() else 0,
        "removed": row["removed"] if "removed" in row.keys() else 0,
    }


def research_runs(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    """The runs, newest first, each with how many claims it still owns.

    `claims` and `removed` are counted here rather than stored on the run
    because an undo changes them: a denormalised total would be a number that
    silently stops being true the moment the feature it exists for is used.
    """
    return [
        _research_run(row)
        for row in conn.execute(
            "SELECT r.*,"
            " (SELECT COUNT(*) FROM research_run_claims c"
            "   WHERE c.run_id = r.run_id AND c.removed_at IS NULL) AS claims,"
            " (SELECT COUNT(*) FROM research_run_claims c"
            "   WHERE c.run_id = r.run_id AND c.removed_at IS NOT NULL) AS removed"
            " FROM research_runs r ORDER BY r.started_at DESC LIMIT ?",
            (limit,),
        )
    ]


#: The columns a run can be metered in, and the plain-language answer to
#: "why is this one empty". Kept beside the aggregate rather than in the
#: interface, because whether a column *can* be filled is a fact about the
#: plane and not a rendering choice — a screen that invented the sentence
#: would drift from the schema the first time a plane learned to count.
METERED = ("spent_usd", "tokens_used")


def usage_totals(conn: sqlite3.Connection) -> dict:
    """What every run has cost, together, and what that buys per claim.

    The per-run rows have always said what one run spent. Nobody could ask the
    only question a reader actually has — *what has this cost me so far, and
    is it worth it* — because that answer is a sum, and there was nowhere to
    read a sum from.

    Two habits from the per-run column carry over, and both are about the
    difference between zero and unknown:

    * `runs` and `metered_runs` are both reported. A total of $0.14 over two
      hundred runs means something very different depending on whether two of
      them were counted or all two hundred were, and a lone total cannot say
      which.
    * `cost_per_claim` is None rather than 0.0 whenever the numerator is
      unmeasured or the denominator is zero. A cost-per-claim of "$0.00" on an
      installation that has never metered anything is a lie with a decimal
      point on it, and it is the number a reader would quote.

    `claims` counts what the runs still own — an undone run has given its
    claims back, and the cost of a run whose claims are gone is a sunk cost
    rather than a cheaper claim.
    """
    row = conn.execute(
        "SELECT COUNT(*) AS runs,"
        " SUM(CASE WHEN spent_usd IS NOT NULL THEN 1 ELSE 0 END) AS metered_runs,"
        " SUM(CASE WHEN tokens_used IS NOT NULL THEN 1 ELSE 0 END) AS counted_runs,"
        " SUM(spent_usd) AS spent_usd, SUM(tokens_used) AS tokens_used"
        " FROM research_runs"
    ).fetchone()
    claims = conn.execute(
        "SELECT COUNT(*) FROM research_run_claims WHERE removed_at IS NULL"
    ).fetchone()[0]
    spent = row["spent_usd"]
    planes = [
        {
            "plane": item["plane"] or "",
            "runs": item["runs"],
            "metered_runs": item["metered_runs"],
            "spent_usd": item["spent_usd"],
            "tokens_used": item["tokens_used"],
        }
        for item in conn.execute(
            "SELECT plane, COUNT(*) AS runs,"
            " SUM(CASE WHEN spent_usd IS NOT NULL THEN 1 ELSE 0 END) AS metered_runs,"
            " SUM(spent_usd) AS spent_usd, SUM(tokens_used) AS tokens_used"
            " FROM research_runs GROUP BY plane ORDER BY runs DESC, plane"
        )
    ]
    return {
        "runs": row["runs"] or 0,
        "metered_runs": row["metered_runs"] or 0,
        "counted_runs": row["counted_runs"] or 0,
        "spent_usd": spent,
        "tokens_used": row["tokens_used"],
        "claims": claims,
        "cost_per_claim": (
            float(spent) / claims if spent is not None and claims else None
        ),
        "planes": planes,
    }


def get_research_run(conn: sqlite3.Connection, run_id: str) -> dict | None:
    row = conn.execute(
        "SELECT r.*,"
        " (SELECT COUNT(*) FROM research_run_claims c"
        "   WHERE c.run_id = r.run_id AND c.removed_at IS NULL) AS claims,"
        " (SELECT COUNT(*) FROM research_run_claims c"
        "   WHERE c.run_id = r.run_id AND c.removed_at IS NOT NULL) AS removed"
        " FROM research_runs r WHERE r.run_id = ?",
        (run_id,),
    ).fetchone()
    return _research_run(row) if row else None


def run_claims(conn: sqlite3.Connection, run_id: str) -> list[dict]:
    return [
        {
            "pack_id": row["pack_id"],
            "claim_id": row["claim_id"],
            "subject_id": row["subject_id"],
            "title": row["title"],
            "removed_at": row["removed_at"] or "",
        }
        for row in conn.execute(
            "SELECT * FROM research_run_claims WHERE run_id = ? ORDER BY rowid",
            (run_id,),
        )
    ]


def mark_claim_removed(
    conn: sqlite3.Connection, run_id: str, pack_id: str, claim_id: str
) -> None:
    conn.execute(
        "UPDATE research_run_claims SET removed_at = ?"
        " WHERE run_id = ? AND pack_id = ? AND claim_id = ?",
        (_now(), run_id, pack_id, claim_id),
    )
