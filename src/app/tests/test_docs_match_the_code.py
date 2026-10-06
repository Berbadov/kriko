"""The docs are checked by a test, not by someone reading them.

B78. Ten of the twelve tables in `app.sqlite` were named in no document at
all, and five subsystems that landed for 1.0.0 — the pipeline event spine, the
runtime adapter sync, the unmapped-label ledger, the version handshake, the
schema reconciler — appeared nowhere either. That is not a docs problem, it is
the shape of every docs problem: prose does not fail, so it drifts silently and
the audit that finds it is a person re-reading files (backlog B43, "the prose
gate is a worklist, not a proof").

So the checks below are all *derived*, never a list written here. Each asks a
question of the code and looks for the answer in a document. A new table, a new
router, a new interface surface — each one shows up as a red test the day it
lands, which is the only version of a documentation audit that runs unattended
(G5's automation principle).

What this deliberately does not check: whether the prose is *correct*. Nothing
mechanical can. It checks that the thing exists in the sentence-writing
surface at all, which is the failure that actually happened.
"""

import re
from pathlib import Path

import pytest

from app import extension
from app.web import state
from app.web.app import create_app
from app.web.settings import Settings

ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / "docs"


def read(*names: str) -> str:
    """Everything named, concatenated. Which file says it is not the point."""
    return "\n".join((ROOT / name).read_text(encoding="utf-8") for name in names)


@pytest.fixture(scope="module")
def prose() -> str:
    files = ["README.md", "CLAUDE.md"]
    files += [
        str(path.relative_to(ROOT))
        for path in sorted(DOCS.glob("*.md"))
    ]
    return read(*files)


def test_it_is_reading_the_documents(prose):
    # A fixture that silently returns "" passes every assertion below.
    assert len(prose) > 20_000
    assert "INTERNALS" in prose or "Request Path" in prose


def test_every_interface_table_is_written_down(prose):
    """`app.sqlite` is the reader's own history — the one file we can never
    drop and rebuild, and therefore the one whose shape has to be legible to
    someone deciding whether a change to it is safe."""
    undocumented = [name for name in sorted(state.declared_columns()) if name not in prose]
    assert not undocumented, (
        f"{undocumented} are tables in app.sqlite that no document names. "
        "They hold a reader's history and settings; a table nobody wrote down "
        "is a table the next change will treat as a cache. "
        "docs/INTERNALS.md has the table of them."
    )


def test_the_split_between_the_two_databases_is_stated(prose):
    # The rule that keeps history out of the engine's schema. Stated in
    # CLAUDE.md and INTERNALS.md, because it is the one a new interface
    # surface breaks by accident.
    assert "app.sqlite" in prose and "knowledge.sqlite" in prose


def test_the_version_floor_is_documented_by_name(prose):
    # Not the value — that moves. The name, so the reader of the docs can
    # find the one place it lives.
    assert "MINIMUM_VERSION" in prose
    assert extension.VERSION_HEADER.lower() in prose.lower()
    assert extension.MINIMUM_HEADER.lower() in prose.lower()


def test_every_api_surface_has_an_endpoint_in_the_docs(prose, tmp_path):
    """A router is a whole surface — a door into the engine that someone has to
    know exists before they can reason about it.

    By *endpoint*, not by module name. The first version of this asked whether
    the string "focus" appeared, and it did — in every sentence about where
    focus lands after navigation. So the check passed while
    `routers/focus.py`, the surface that fixes "Open in App opens a browser
    tab instead of the app", was documented nowhere at all. A router whose
    name is also an English word is exactly the one a name check misses.

    An endpoint path is also the right granularity: it is what the docs
    already write (`GET /api/jobs`), and it is what a reader of the docs
    actually needs in order to go and look.
    """
    app = create_app(
        Settings.from_env(
            store_path=tmp_path / "knowledge.sqlite",
            app_state_path=tmp_path / "app.sqlite",
            analysis_log_path=tmp_path / "analyses.jsonl",
        )
    )
    surfaces: dict[str, set[str]] = {}

    def walk(routes) -> None:
        # Recursive, and through `original_router`: this FastAPI keeps one
        # `_IncludedRouter` per `include_router` call rather than flattening
        # the endpoints into `app.routes`, so the obvious one-level loop finds
        # nothing at all and an `assert len(surfaces) > 10` is what says so.
        for route in routes:
            module = getattr(getattr(route, "endpoint", None), "__module__", "")
            path = getattr(route, "path", "")
            if module.startswith("app.web.routers.") and path.startswith("/api"):
                surfaces.setdefault(module.rsplit(".", 1)[-1], set()).add(path)
            walk(getattr(route, "routes", ()))
            nested = getattr(route, "original_router", None)
            if nested is not None:
                walk(nested.routes)

    walk(app.routes)

    assert len(surfaces) > 10, f"only found {sorted(surfaces)} — has the package moved?"
    undocumented = sorted(
        name
        for name, paths in surfaces.items()
        # The literal prefix before any path parameter, so `/api/jobs/{id}`
        # is satisfied by prose that writes `/api/jobs/{job_id}`.
        if not any(path.split("{")[0].rstrip("/") in prose for path in paths)
    )
    assert not undocumented, (
        f"{undocumented} are API surfaces with no endpoint named in any "
        "document. docs/INTERNALS.md's planes are where a surface gets "
        f"introduced. Their paths: "
        + "; ".join(f"{n}: {sorted(surfaces[n])[0]}" for n in undocumented)
    )


def test_the_documentation_map_names_files_that_exist():
    """CLAUDE.md's table is the entry point to every other document, so a row
    pointing at a moved file sends the next session to nothing."""
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    # Only what is written as a path. A bare backticked filename in prose is
    # a *name* — the historical row names `handover.md` and `SCAFFOLD.md`
    # inside a parenthetical about the directory holding them, and reading
    # those as repo-root paths would fail on documents that are exactly where
    # the sentence says they are.
    cited = set(re.findall(r"`([\w.-]+(?:/[\w.-]+)+\.md)`", claude))
    assert len(cited) > 5, "the documentation map cites almost nothing — has it moved?"
    missing = sorted(
        name
        for name in cited
        if "<" not in name and not (ROOT / name).exists()
    )
    assert not missing, (
        f"CLAUDE.md cites {missing}, which are not on disk. A stale pointer in "
        "the documentation map is worse than no pointer: it costs a session a "
        "search before it concludes the file is gone."
    )
