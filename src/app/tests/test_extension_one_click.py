"""The one click that is actually available.

`app/extension.py`'s own docstring says no application may install a browser
extension, and that is true: nothing here asks a *running* browser to load
anything, and `chrome://extensions` still cannot be opened from a command
line.

What it missed is the other door. A Chromium browser we start ourselves takes
`--load-extension` on its command line, so the app can hand the reader a
window that already has Kriko in it — one click instead of stage, reveal,
open the browser, find developer mode, drag the folder.

Two things make this honest rather than a trick:

* **A profile of our own.** Passing `--load-extension` to a browser that is
  already running does nothing at all — the arguments are forwarded to the
  existing process, which ignores them. `--user-data-dir` is what makes the
  launch a new browser instead of a no-op, and the reader is told it is a
  separate profile rather than discovering it by finding no bookmarks.
* **The check-in is the proof.** Chrome has restricted this flag before and
  will again. So the button does not *claim* success: the extension calling
  `/api/adapters` is what says it worked, the page already watches for that
  sighting, and the manual steps stay on screen until it lands. Failing open,
  in the automation principle's sense.
"""

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import extension, sites
from app.web.routers import extension as ext_router
from app.web.app import create_app
from app.web.settings import Settings


def _staged(tmp_path):
    """A staged folder as `extension.stage` leaves it — manifest and all.

    The manifest is the only file `launch_with_extension` looks for, because a
    browser pointed at a directory with no manifest in it loads no extension
    and reports nothing: it just opens.
    """
    staged = tmp_path / "extension"
    staged.mkdir(exist_ok=True)
    (staged / "manifest.json").write_text('{"version": "0.4.0"}', encoding="utf-8")
    return staged


def _client(tmp_path, **over):
    return TestClient(
        create_app(
            Settings(
                store_path=tmp_path / "knowledge.sqlite",
                app_state_path=tmp_path / "app.sqlite",
                analysis_log_path=tmp_path / "analyses.jsonl",
                **over,
            )
        )
    )


# ── finding a browser ────────────────────────────────────────────────────


def test_a_browser_is_found_by_looking_where_they_are(tmp_path, monkeypatch):
    """Candidates are paths and command names, tried in order.

    Not a registry read and not a per-platform detection library: the question
    is "is there a Chromium here", the answer is a file that exists, and a
    closed list of the four names Chromium ships under is exactly the fixed
    vocabulary the scalability principle allows as a constant.
    """
    fake = tmp_path / "chrome"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setattr(extension, "_candidates", lambda: [str(fake)])

    found = extension.find_chromium()
    assert found == str(fake)


def test_no_browser_is_a_none_not_an_exception(monkeypatch):
    """An install with no Chromium is a Firefox reader, not a broken machine.

    They get the manual steps, which work — so this path must degrade to "we
    could not offer you the shortcut", never to a traceback on the page
    someone opened for help.
    """
    monkeypatch.setattr(extension, "_candidates", lambda: ["/nowhere/chrome"])
    assert extension.find_chromium() is None


def test_the_candidate_list_names_the_four_chromium_browsers(monkeypatch):
    names = " ".join(extension._candidates()).lower()
    for word in ("chrome", "chromium", "brave", "edge"):
        assert word in names


# ── launching it ─────────────────────────────────────────────────────────


def test_the_launch_carries_the_extension_and_a_profile_of_its_own(tmp_path):
    """The two arguments that make this work at all.

    Without `--load-extension` there is no extension; without
    `--user-data-dir` the arguments reach an already-running browser that
    ignores them, and the button does nothing while looking like it worked —
    the worst of the available outcomes.
    """
    spawned: list[list[str]] = []
    staged = _staged(tmp_path)
    profile = tmp_path / "browser"

    error = extension.launch_with_extension(
        "/usr/bin/chrome", staged, profile, spawn=spawned.append
    )

    assert error == ""
    (argv,) = spawned
    assert argv[0] == "/usr/bin/chrome"
    assert f"--load-extension={staged}" in argv
    assert f"--user-data-dir={profile}" in argv
    # A fresh profile otherwise opens on "make me your default browser" and a
    # sign-in wall, which is three dialogs between the reader and the thing
    # they pressed a button for.
    assert "--no-first-run" in argv
    # The third argument that makes it work, added 2026-09-14. Chrome turned
    # `--load-extension` off by default as an anti-malware measure, so without
    # this the flag above is a silent no-op: the window opens, the landing page
    # loads, the extension is absent, and every visible thing worked. That was
    # the 0.8.0 report.
    #
    # Measured on Chromium 141 by launching with `--remote-debugging-port` and
    # counting `chrome-extension://` targets: 0 without this flag, 2 with it.
    assert "--disable-features=DisableLoadExtensionCommandLineSwitch" in argv
    assert "--no-default-browser-check" in argv


def test_the_window_opens_on_a_page_rather_than_a_blank_tab(tmp_path):
    """A browser that opens on a blank tab has not told the reader anything.

    This is the mechanism only — the argument reaches the command line.
    *Which* page it should be is the endpoint's decision and is asserted at
    the bottom of this file; it used to be this app's own screen, and that was
    the defect.
    """
    spawned: list[list[str]] = []
    staged = _staged(tmp_path)

    extension.launch_with_extension(
        "/usr/bin/chrome",
        staged,
        tmp_path / "browser",
        landing="http://127.0.0.1:1234/#/extension",
        spawn=spawned.append,
    )

    assert "http://127.0.0.1:1234/#/extension" in spawned[0]


def test_a_launch_that_cannot_start_says_so_instead_of_raising(tmp_path):
    staged = _staged(tmp_path)

    def refuse(argv):
        raise OSError("Permission denied")

    error = extension.launch_with_extension(
        "/usr/bin/chrome", staged, tmp_path / "browser", spawn=refuse
    )
    assert "Permission denied" in error


def test_nothing_staged_is_refused_before_a_browser_is_started(tmp_path):
    """A browser pointed at a directory that does not exist loads no
    extension and reports nothing — it just opens. Cheaper to notice here."""
    error = extension.launch_with_extension(
        "/usr/bin/chrome", tmp_path / "missing", tmp_path / "browser", spawn=lambda a: None
    )
    assert "nothing staged" in error


# ── the endpoint ─────────────────────────────────────────────────────────


def test_one_call_stages_and_opens(tmp_path, monkeypatch):
    """One click, so one request: the endpoint stages first.

    Making the page call `/stage` and then `/launch` would put the reader's
    one click behind two round trips that can half-fail — staged but no
    browser, which reads as "it did nothing".
    """
    spawned: list[list[str]] = []
    monkeypatch.setattr(extension, "find_chromium", lambda: "/usr/bin/chrome")
    monkeypatch.setattr(extension, "_spawn", spawned.append)

    client = _client(tmp_path)
    body = client.post("/api/extension/launch").json()

    assert body["launched"] is True
    assert body["browser"] == "/usr/bin/chrome"
    assert (tmp_path / "extension" / "manifest.json").is_file()
    assert f"--load-extension={tmp_path / 'extension'}" in spawned[0]
    # The profile lives beside the store, for the same reason the staged
    # extension does: an install directory is replaced wholesale on update.
    assert f"--user-data-dir={tmp_path / 'browser-profile'}" in spawned[0]


def test_no_chromium_is_a_plain_answer_not_a_failed_request(tmp_path, monkeypatch):
    """The Firefox reader presses the button once and needs to be told why it
    is not for them — with the steps that are, which the page already has."""
    monkeypatch.setattr(extension, "find_chromium", lambda: None)

    client = _client(tmp_path)
    response = client.post("/api/extension/launch")

    assert response.status_code == 200
    body = response.json()
    assert body["launched"] is False
    assert "chromium" in body["error"].lower() or "chrome" in body["error"].lower()
    # Staged anyway: the manual path needs the files, and the reader who
    # pressed this button wants them there either way.
    assert (tmp_path / "extension" / "manifest.json").is_file()


def test_the_reader_is_told_it_is_a_separate_profile(tmp_path, monkeypatch):
    """Discovering the absence of your own bookmarks is a bug report.

    The window is a second profile by necessity, and the response says so, so
    the page can say so before the window opens rather than after.
    """
    monkeypatch.setattr(extension, "find_chromium", lambda: "/usr/bin/chrome")
    monkeypatch.setattr(extension, "_spawn", lambda argv: None)

    body = _client(tmp_path).post("/api/extension/launch").json()

    assert body["profile"] == str(tmp_path / "browser-profile")
    assert "profile" in body["note"].lower()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX session semantics")
def test_the_browser_outlives_this_process_group(tmp_path):
    """A browser started in our process group dies with the sidecar.

    The reader closes the Kriko window, their browser vanishes mid-listing,
    and nothing on screen explains why. `start_new_session` is the one flag
    that matters here and it is invisible in every test that mocks the spawn,
    so it is asserted on the real call.
    """
    import inspect

    source = inspect.getsource(extension._spawn)
    assert "start_new_session" in source


# ── where the window opens ───────────────────────────────────────────────
#
# The reader's report of the first version of this, verbatim: "open with
# extension just opens the app interface in the web browser, exact copy of the
# standalone app. I originally meant the hovering web extension." The landing
# page was this app's own `/#/extension`, chosen so the check-in confirmation
# would be the first thing they saw — and on that page the extension is, by
# construction, invisible: it matches listing sites, and this is not one. So a
# button whose entire purpose is "show me the thing in the browser" opened a
# browser where the thing does nothing.
#
# It now lands on a site an installed pack can read, and the confirmation
# stays where the reader already is: the status card on this screen polls.


def _landed(client, monkeypatch, site_names):
    """The URL a launch put on the browser's command line."""
    spawned: list[list[str]] = []
    monkeypatch.setattr(extension, "find_chromium", lambda: "/usr/bin/chrome")
    monkeypatch.setattr(extension, "_spawn", spawned.append)
    monkeypatch.setattr(
        sites,
        "registered",
        lambda store, app_conn: [
            {"site": s, "source": "pack", "superseded": False} for s in site_names
        ],
    )
    body = client.post("/api/extension/launch").json()
    return body, spawned[0]


def test_the_window_opens_where_the_extension_has_something_to_do(tmp_path, monkeypatch):
    client = _client(tmp_path)
    body, argv = _landed(client, monkeypatch, ["listings.example"])

    assert body["landing"] == "https://listings.example/"
    assert "https://listings.example/" in argv
    # The defect itself: a browser opened on a second copy of this app.
    assert not any("#/extension" in arg for arg in argv)


@pytest.mark.parametrize("site", ["listings.example", "second-site.example"])
def test_the_landing_page_is_pack_data(site, tmp_path, monkeypatch):
    """Which listing sites exist is a pack's business, not the app's.

    An app that hardcoded one would have to be edited to ship a second
    category, which is the layering rule this whole codebase is arranged
    around. So the site is read off the adapter rows, and this asserts both
    halves: the value follows the data, and the router names no site itself.
    """
    body, _ = _landed(_client(tmp_path), monkeypatch, [site])
    assert body["landing"] == f"https://{site}/"

    source = Path(ext_router.__file__).read_text(encoding="utf-8")
    assert not re.search(r"https?://[a-z0-9.-]+\.(com|net|org|tr)", source), (
        "a site named in the router is a category the engine knows about"
    )


def test_a_site_the_reader_taught_this_install_is_a_landing_page_too(
    tmp_path, monkeypatch
):
    """A locally-learned site (`app/sites.py`) is not a pack's, but it is
    readable, and the launch button's whole job is "open somewhere the
    extension has something to do". Before this, `_landing` read `load_adapters`
    directly — the packs' rows only — so a reader whose one readable site was
    one they registered themselves (no pack ships an adapter for it) still fell
    back to `#/extension`, the exact failure this button exists to fix.
    """
    client = _client(tmp_path)
    spawned: list[list[str]] = []
    monkeypatch.setattr(extension, "find_chromium", lambda: "/usr/bin/chrome")
    monkeypatch.setattr(extension, "_spawn", spawned.append)
    monkeypatch.setattr(
        sites,
        "registered",
        lambda store, app_conn: [
            {"site": "arabam.example", "source": "local", "superseded": False}
        ],
    )
    body = client.post("/api/extension/launch").json()
    assert body["landing"] == "https://arabam.example/"
    assert "https://arabam.example/" in spawned[0]


def test_a_superseded_local_site_is_skipped_for_the_pack_row_that_replaced_it(
    tmp_path, monkeypatch
):
    """A pack that now ships an adapter for a host the reader taught locally
    makes the local row `superseded` (`app/sites.py`); landing on it would
    open the same host twice for no reason, so it is skipped in favour of the
    pack's own row.
    """
    client = _client(tmp_path)
    spawned: list[list[str]] = []
    monkeypatch.setattr(extension, "find_chromium", lambda: "/usr/bin/chrome")
    monkeypatch.setattr(extension, "_spawn", spawned.append)
    monkeypatch.setattr(
        sites,
        "registered",
        lambda store, app_conn: [
            {"site": "arabam.example", "source": "local", "superseded": True},
            {"site": "arabam.example", "source": "pack", "superseded": False},
        ],
    )
    body = client.post("/api/extension/launch").json()
    assert body["landing"] == "https://arabam.example/"


def test_with_no_pack_installed_the_app_screen_is_the_fallback(tmp_path, monkeypatch):
    """There is no listing site to open, and a blank tab explains nothing.

    This is the one case the old behaviour was right for: with no adapter
    there is nothing for the extension to match anywhere, and the screen that
    says what to do next is better than a browser's default page.
    """
    body, argv = _landed(_client(tmp_path), monkeypatch, [])

    assert body["landing"].endswith("/#/extension")
    assert any("#/extension" in arg for arg in argv)
