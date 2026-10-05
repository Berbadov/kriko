"""The version handshake, and the header names it rides on.

B73: the extension and the app update on separate clocks — which is right,
knowledge moves weekly and the binary rarely — and neither checked the other.
An unpacked extension is loaded once and stays loaded, so a reader can run a
months-old copy while `/api/extension` reports both the shipped and the staged
version as current. Nothing failed; the panel answered oddly, which from the
reader's side is a broken app.

The rule is one number in one place: `MINIMUM_VERSION`. Not a compatibility
matrix — three moving clocks would make a matrix wrong within a release — and
not a version table in the extension, which would be the same list twice.
"""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import extension
from app.web.app import create_app
from app.web.settings import Settings

BACKGROUND = Path(extension.__file__).resolve().parent.parent.parent / "extension"
ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"


@pytest.fixture
def client(tmp_path):
    app = create_app(
        Settings.from_env(
            store_path=tmp_path / "knowledge.sqlite",
            app_state_path=tmp_path / "app.sqlite",
            analysis_log_path=tmp_path / "analyses.jsonl",
        )
    )
    with TestClient(app) as test_client:
        yield test_client


def hit(client, version=None):
    headers = {"origin": ORIGIN}
    if version is not None:
        headers[extension.VERSION_HEADER] = version
    return client.get("/api/health", headers=headers)


# ── the rule ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected",
    [
        ("0.3.0", (0, 3, 0)),
        ("1.2", (1, 2)),
        ("1.0.0-rc1", (1, 0, 0)),
        ("", ()),
        ("nonsense", ()),
        ("v1.0", ()),  # the leading letter stops it; "" sorts below everything
    ],
)
def test_a_version_is_parsed_or_admitted_to_be_unparseable(text, expected):
    assert extension.parse_version(text) == expected


def test_no_version_sorts_below_every_real_one():
    # The blank an extension too old to send the header leaves behind is
    # meant to read as "older than anything that can speak".
    assert extension.parse_version("") < extension.parse_version("0.0.1")


def test_an_extension_below_the_floor_is_too_old():
    verdict = extension.compatibility("0.1.0", "0.3.0")
    assert verdict["state"] == "too_old"
    assert "0.1.0" in verdict["detail"]
    assert extension.MINIMUM_VERSION in verdict["detail"]


def test_an_extension_the_app_has_never_heard_from_is_unknown_not_stale():
    # Separate states because they call for opposite sentences: telling a
    # reader who has not installed the extension that theirs is out of date is
    # worse than saying nothing.
    verdict = extension.compatibility("", "0.3.0")
    assert verdict["state"] == "unknown"
    assert verdict["detail"] == ""


def test_an_extension_older_than_what_ships_but_above_the_floor_still_works():
    verdict = extension.compatibility("0.3.0", "0.9.0")
    assert verdict["state"] == "behind"
    assert "still works" in verdict["detail"]


def test_the_shipped_extension_clears_its_own_floor():
    # A release that ships an extension its own app refuses is a packaging
    # bug that no other test would catch, and the reader would meet it as
    # "reload the extension" advice that cannot help.
    manifest = json.loads((BACKGROUND / "manifest.json").read_text(encoding="utf-8"))
    shipped = extension.parse_version(manifest["version"])
    assert shipped >= extension.parse_version(extension.MINIMUM_VERSION)


# ── the wire ────────────────────────────────────────────────────────────


def test_the_app_states_its_floor_on_every_answer(client):
    # On the response, not at an endpoint: a compatibility check that needs a
    # second request is a check that fails whenever the first one does.
    response = client.get("/api/health")
    assert response.headers[extension.MINIMUM_HEADER] == extension.MINIMUM_VERSION


def test_the_floor_is_readable_by_the_caller_that_needs_it(client):
    # A header a browser will not let a caller read is a header that does not
    # exist. The worker's own fetches are CORS-exempt through
    # `host_permissions`, but the allowlist is what makes that not a thing to
    # remember.
    exposed = client.get("/api/health").headers["access-control-expose-headers"]
    assert extension.MINIMUM_HEADER in exposed.lower()


def test_the_running_version_is_learned_from_work_it_was_doing_anyway(client):
    hit(client, "0.2.1")
    status = client.get("/api/extension").json()
    assert status["compatibility"]["running_version"] == "0.2.1"
    assert status["compatibility"]["state"] == "too_old"


def test_a_request_without_the_header_does_not_erase_what_we_knew(client):
    # An older surface, a different browser, a request from a page — none of
    # them should turn a known version into an unknown one.
    hit(client, "0.3.0")
    hit(client, None)
    status = client.get("/api/extension").json()
    assert status["compatibility"]["running_version"] == "0.3.0"


def test_a_newer_extension_replaces_the_version_we_had(client):
    hit(client, "0.2.1")
    hit(client, "0.4.0")
    status = client.get("/api/extension").json()
    assert status["compatibility"]["running_version"] == "0.4.0"


def test_a_version_header_is_stored_but_never_trusted(client):
    # It is a header, so it is whatever the caller sent. Displayed and
    # compared, never executed — and truncated, because a header is not a
    # place to put a payload.
    hit(client, "x" * 500)
    row = client.get("/api/extension").json()["sightings"][0]
    assert len(row["version"]) <= 32


def test_the_app_says_what_it_ships_so_the_extension_page_can_compare(client):
    health = client.get("/api/health").json()
    assert health["minimum_extension_version"] == extension.MINIMUM_VERSION
    # Present even when empty: a bundle built without the extension is a
    # packaging shape, not a fault, and /api/health is what the shell polls
    # before it will show a window at all.
    assert "extension_version" in health


def test_nothing_has_called_yet_reads_as_unknown_not_as_a_fault(client):
    status = client.get("/api/extension").json()
    assert status["compatibility"]["state"] == "unknown"


# ── one name, two languages ─────────────────────────────────────────────


def test_both_headers_are_spelled_the_same_on_both_sides():
    # The gate that was missing. Two files in two languages agree on two
    # strings, and a rename in either one is silent: the extension keeps
    # working, the app keeps answering, and the version is simply never
    # learned. Same reasoning as the sidecar's `KRIKO_PORT` handshake test.
    source = (BACKGROUND / "background.js").read_text(encoding="utf-8")
    for header in (extension.VERSION_HEADER, extension.MINIMUM_HEADER):
        found = re.findall(rf'"({header})"', source, re.IGNORECASE)
        assert found, f"background.js never names {header}"


def test_the_extension_holds_no_version_floor_of_its_own():
    # The comparison lives in the extension; the *rule* lives here. A floor
    # written in both would be the compatibility matrix this design exists to
    # avoid, and the copies would disagree without failing.
    source = (BACKGROUND / "background.js").read_text(encoding="utf-8")
    quoted = re.escape(extension.MINIMUM_VERSION)
    assert not re.search(rf'["\']{quoted}["\']', source)
