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
import secrets
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

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
    hits     INTEGER NOT NULL DEFAULT 1
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
CREATE TABLE IF NOT EXISTS submissions (
    submission_id TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    door          TEXT NOT NULL,
    subject_id    TEXT NOT NULL,
    pack_id       TEXT NOT NULL,
    accepted      INTEGER NOT NULL DEFAULT 0,
    refused       INTEGER NOT NULL DEFAULT 0,
    verdicts_json TEXT NOT NULL
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
"""

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
        conn.execute(f"PRAGMA user_version = {stamp}")
        conn.commit()
    return conn


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


def record_extension(conn: sqlite3.Connection, origin: str) -> None:
    """Note that an extension origin reached us just now.

    Deliberately cheap and deliberately silent. It runs inside a middleware on
    a request the extension is waiting on, so it must not raise: a locked
    database or a schema older than this table would otherwise turn "the
    reader installed the extension" into "the extension reports the app is
    broken", which is precisely backwards.
    """
    now = _now()
    try:
        conn.execute(
            "INSERT INTO extension_seen (origin, first_at, last_at, hits)"
            " VALUES (?, ?, ?, 1)"
            " ON CONFLICT(origin) DO UPDATE SET last_at = excluded.last_at,"
            " hits = extension_seen.hits + 1",
            (origin, now, now),
        )
        conn.commit()
    except sqlite3.Error:
        pass


def extension_sightings(conn: sqlite3.Connection) -> list[dict]:
    """Every extension origin that has ever called, newest contact first."""
    return [
        dict(row)
        for row in conn.execute(
            "SELECT origin, first_at, last_at, hits FROM extension_seen"
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
        " pack_id, accepted, refused, verdicts_json) VALUES (?,?,?,?,?,?,?,?)",
        (
            submission_id,
            _now(),
            door if door in DOORS else "job",
            subject_id,
            pack_id,
            len(accepted),
            len(refused),
            json.dumps(verdicts, default=str),
        ),
    )
    conn.commit()
    return submission_id


def _submission(row: sqlite3.Row) -> dict:
    out = dict(row)
    out["verdicts"] = json.loads(out.pop("verdicts_json") or "{}")
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


# ── jobs ─────────────────────────────────────────────────────────────────
#
# `queued -> running -> (succeeded | failed | cancelled | interrupted)`.
# `interrupted` is not an error state a handler can produce: it is what a row
# left `running` by a killed process becomes at the next startup, so a lost job
# is visible as a state rather than as a spinner nobody can explain.

QUEUED, RUNNING = "queued", "running"
SUCCEEDED, FAILED, CANCELLED, INTERRUPTED = (
    "succeeded",
    "failed",
    "cancelled",
    "interrupted",
)
TERMINAL = frozenset({SUCCEEDED, FAILED, CANCELLED, INTERRUPTED})


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
    sets, args = [], []
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
    if row["state"] == RUNNING:
        conn.execute(
            "UPDATE jobs SET cancel_requested = 1, message = ? WHERE job_id = ?",
            ("cancelling…", job_id),
        )
        conn.commit()
        return RUNNING
    return row["state"]


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


def interrupt_running(conn: sqlite3.Connection) -> int:
    """Called at startup. Anything still `running` belongs to a dead process."""
    cursor = conn.execute(
        "UPDATE jobs SET state = ?, finished_at = ?, message = ?"
        " WHERE state IN (?, ?)",
        (
            INTERRUPTED,
            _now(),
            "the server stopped while this was running",
            RUNNING,
            QUEUED,
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
