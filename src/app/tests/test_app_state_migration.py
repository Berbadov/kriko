"""A column added to SCHEMA has to reach a file that already exists.

Found while adding `extension_seen.version` for B73. Every previous change to
this schema was a *new table*, and `CREATE TABLE IF NOT EXISTS` handles those
— which is exactly why nobody noticed that it does nothing at all for a new
column. The stamp moves, `executescript` runs, `PRAGMA user_version` is
rewritten, and the column is silently absent until the first query names it.
Then every history view fails at once, on the reader's machine, against the
reader's own data, with `no such column`.

`app.sqlite` is history and settings, not a cache: it cannot be dropped and
rebuilt. So the reconciler only ever *adds*, reads what to add off the
declaration rather than off a migration list someone has to remember to
extend, and raises rather than papering over anything SQLite refuses.
"""

import re
import sqlite3

import pytest

from app.web import state


def test_the_declaration_is_parsed_not_hand_listed():
    # If this drops a table, everything below is checking a shorter list than
    # the schema actually has, and the next missed column is invisible again.
    declared = state.declared_columns()
    # Line-initial, because the module's own prose mentions the statement and
    # a substring count would have quietly agreed with a parser that missed a
    # table.
    statements = re.findall(r"(?m)^CREATE TABLE", state.SCHEMA)
    assert len(statements) == len(declared)
    assert declared["extension_seen"]["version"].startswith("version")


def test_a_table_constraint_is_not_mistaken_for_a_column():
    # `PRIMARY KEY (adapter_id, label)` would otherwise be read as a column
    # called "PRIMARY", and the reconciler would try to ALTER one in.
    columns = state.declared_columns()["unmapped_labels"]
    assert set(columns) == {
        "adapter_id", "label", "seen", "first_at", "last_at", "sample_url",
    }


def test_a_comma_inside_a_constraint_does_not_split_a_column():
    sql = """
CREATE TABLE IF NOT EXISTS t (
    a TEXT NOT NULL,
    b TEXT NOT NULL DEFAULT '',
    -- a comment, with a comma in it
    PRIMARY KEY (a, b)
);
"""
    assert set(state.declared_columns(sql)["t"]) == {"a", "b"}


def test_a_column_added_to_the_schema_reaches_an_existing_file(tmp_path):
    path = tmp_path / "app.sqlite"
    # A file from before the column existed, written the way the old schema
    # would have written it — the actual shape on a reader's disk.
    old = sqlite3.connect(path)
    old.executescript(
        "CREATE TABLE extension_seen ("
        " origin TEXT PRIMARY KEY, first_at TEXT NOT NULL,"
        " last_at TEXT NOT NULL, hits INTEGER NOT NULL DEFAULT 1);"
    )
    old.execute(
        "INSERT INTO extension_seen (origin, first_at, last_at, hits)"
        " VALUES ('chrome-extension://old', 'then', 'then', 7)"
    )
    old.commit()
    old.close()

    conn = state.connect(path)
    rows = state.extension_sightings(conn)
    # Both halves matter: the column arrived, and the row that predates it is
    # still there. A migration that reached the first by losing the second
    # would be the worse bug.
    assert rows[0]["version"] == ""
    assert rows[0]["hits"] == 7
    conn.close()


def test_the_reconciler_reports_exactly_what_it_added(tmp_path):
    path = tmp_path / "app.sqlite"
    conn = sqlite3.connect(path)
    conn.executescript("CREATE TABLE extension_seen (origin TEXT PRIMARY KEY);")
    conn.commit()
    added = state.add_missing_columns(conn)
    assert set(added) == {
        "extension_seen.first_at",
        "extension_seen.last_at",
        "extension_seen.hits",
        "extension_seen.version",
    }
    conn.close()


def test_reconciling_a_current_file_changes_nothing(tmp_path):
    # It runs on every schema change, so it has to be a no-op the rest of the
    # time — an ALTER that fires twice is an error, not an idempotent write.
    conn = state.connect(tmp_path / "app.sqlite")
    assert state.add_missing_columns(conn) == []
    assert state.add_missing_columns(conn) == []
    conn.close()


def test_a_column_sqlite_cannot_add_raises_rather_than_going_missing(tmp_path):
    # NOT NULL with no default is the case SQLite refuses on a non-empty
    # table. That is a real migration and has to be written as one — failing
    # loudly at the developer is the whole point, because the alternative is a
    # column that is absent on every reader's machine and present on ours.
    conn = sqlite3.connect(tmp_path / "app.sqlite")
    conn.executescript("CREATE TABLE t (a TEXT);")
    conn.execute("INSERT INTO t (a) VALUES ('x')")
    conn.commit()
    sql = "CREATE TABLE IF NOT EXISTS t (\n    a TEXT,\n    b TEXT NOT NULL\n);"
    with pytest.raises(sqlite3.OperationalError):
        state.add_missing_columns(conn, sql)
    conn.close()


def test_a_table_the_schema_does_not_know_is_left_alone(tmp_path):
    conn = sqlite3.connect(tmp_path / "app.sqlite")
    conn.executescript("CREATE TABLE somebody_elses (x TEXT);")
    conn.commit()
    state.add_missing_columns(conn)
    assert [
        row[1] for row in conn.execute("PRAGMA table_info(somebody_elses)")
    ] == ["x"]
    conn.close()


def test_no_new_column_is_one_sqlite_could_never_add():
    """A ratchet, and the only shape this check can honestly take.

    Most columns below are NOT NULL with no default, and that is fine: they
    shipped *with* their tables, so no reader ever needed them added in place.
    The rule only binds new ones, and "new" needs a baseline — so the baseline
    is written down. Adding a column shows up here as a one-line diff, which
    is the moment to ask whether a reader with an older file can get it.

    Same pattern as the invariant that ratchets `backend/` shut: a frozen set
    is not a hand-maintained list of car data, it is a one-time inventory of a
    thing that must stop growing.
    """
    unaddable = {
        f"{table}.{name}"
        for table, columns in state.declared_columns().items()
        for name, definition in columns.items()
        if "NOT NULL" in definition.upper()
        and "DEFAULT" not in definition.upper()
        and "PRIMARY KEY" not in definition.upper()
    }
    added = unaddable - BACK_THEN
    assert not added, (
        f"{sorted(added)} are NOT NULL with no default, so a reader whose "
        "app.sqlite predates them cannot get them: `ALTER TABLE ADD COLUMN` "
        "refuses. Give each a DEFAULT, or write a real migration and extend "
        "BACK_THEN below."
    )
    # And the other direction, so the inventory cannot rot: a column that
    # gained a default should leave this set rather than sit in it forever.
    assert unaddable <= BACK_THEN


#: Every NOT NULL-without-default column as of 2026-09-08, when
#: `extension_seen.version` revealed that `CREATE TABLE IF NOT EXISTS` does
#: nothing for a new column. Not a list to extend casually — see above.
BACK_THEN = {
    "claim_checks.claim_key", "claim_checks.created_at",
    "claim_checks.lookup_id", "claim_marks.claim_id",
    "claim_marks.created_at", "claim_marks.pack_id",
    "claim_marks.updated_at", "claim_marks.verdict",
    "claim_notes.claim_key", "claim_notes.lookup_id", "claim_notes.note",
    "claim_notes.updated_at", "extension_seen.first_at",
    "extension_seen.last_at", "jobs.created_at", "jobs.kind",
    "jobs.params_json", "jobs.state", "lookups.created_at", "lookups.label",
    "lookups.request_json", "lookups.response_json", "lookups.source",
    "pipeline_events.at", "pipeline_events.message", "pipeline_events.run_id",
    "pipeline_events.stage", "pipeline_runs.kind", "pipeline_runs.started_at",
    "pipeline_runs.state", "pipeline_stages.run_id", "pipeline_stages.seq",
    "pipeline_stages.stage", "pipeline_stages.started_at",
    "pipeline_stages.state", "settings.value", "submissions.created_at",
    "submissions.door", "submissions.pack_id", "submissions.subject_id",
    "submissions.verdicts_json", "unmapped_labels.adapter_id",
    "unmapped_labels.first_at", "unmapped_labels.label",
    "unmapped_labels.last_at",
    # 2026-09-09, and the same rationale as the rest: `fact_checks` arrived as
    # a whole table, so `CREATE TABLE IF NOT EXISTS` gives an older reader all
    # four at once and no `ALTER` is ever asked for. A *fifth* column added to
    # this table later would not have that excuse.
    "fact_checks.pack_id", "fact_checks.claim_id", "fact_checks.verdict",
    "fact_checks.checked_at",
    # 2026-09-09, B86, and the same excuse again: `research_runs` and
    # `research_run_claims` arrived as whole tables. A column added to either
    # of them afterwards has to carry a default.
    "research_runs.started_at", "research_run_claims.run_id",
    "research_run_claims.pack_id", "research_run_claims.claim_id",
    # 2026-09-22, and the excuse holds one more time: `job_messages` arrived
    # whole, so an older file gets all of it from `CREATE TABLE IF NOT
    # EXISTS`. `taken_at` already carries a default because it is the one
    # column a later reply path would want to add in place.
    "job_messages.job_id", "job_messages.body", "job_messages.created_at",
    # 2026-10-02, B193's compare board, and the excuse holds: `compare_questions`
    # arrived as a whole table, so a reader whose file predates it gets all of it
    # from `CREATE TABLE IF NOT EXISTS` and no `ALTER` is ever asked for. The
    # columns that carry a default (`answer`, `job_id`, both timestamps) are the
    # ones a later question path would want to add in place.
    "compare_questions.draft_id", "compare_questions.question_id",
    "compare_questions.question",
}
