"""Regressions from the 0.2.6 bug hunt: fetched pages, redirects, restores, tool calls and search."""

import json
import random
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from app import backups, chat, htmlscan, pricewatch
from app.providers import egress, fetch
from app.web import state
from app.web.settings import Settings
from kriko.store.db import connect

# ── a page chooses its own shape ─────────────────────────────────────────

_DROP = re.compile(r"<(" + "|".join(fetch._DROP_NAMES) + r")(?![\w-])[^>]*>.*?</\1>", re.I | re.S)
_ANCHOR = re.compile(r"<a(?![\w-])[^>]*>(.*?)</a>", re.I | re.S)
_MAIN = re.compile(r"<main(?![\w-])[^>]*>(.*)</main>", re.I | re.S)
_PIECES = ["<nav>", "</nav>", "<NAV class=x>", "</Nav>", "<a href='/x'>", "</a>", "<abbr>", "<a-b>", "text ",
           "<p>", "</p>", "<script>", "</script>", "<style", "<button-group>", "</button>", "<button>", "<",
           "> ", " ", "\n", "<video-js>", "<svg>", "</svg>", "<main>", "</main>"]


def test_the_linear_scanner_returns_what_the_regexes_it_replaced_returned():
    rng = random.Random(7)
    for _ in range(1500):
        page = "".join(rng.choice(_PIECES) for _ in range(rng.randint(1, 25)))
        assert htmlscan.blocks(page, fetch._DROP_NAMES, lambda inner: " ") == _DROP.sub(" ", page)
        assert htmlscan.blocks(page, ("a",), lambda inner: "\x01" + inner + "\x02") == \
            _ANCHOR.sub(lambda m: "\x01" + m.group(1) + "\x02", page)
        main = _MAIN.search(page)
        assert htmlscan.last_block(page, "main") == (main.group(1) if main else None)


@pytest.mark.parametrize("unit", ["<nav>x", '<a href="/p">x', "<nav", "<title>x", "<head>x", "<main>x",
                                  "<script type='application/ld+json'>", "<a x"])
def test_a_page_of_unclosed_tags_is_read_in_the_time_of_a_page(unit):
    page = (unit * (600_000 // len(unit) + 1))[:600_000]
    started = time.monotonic()
    fetch.to_text(page)
    pricewatch.read_markup(page)
    # Quadratic, this was 30 s at a third of the size and an hour at the 2 MB cap.
    assert time.monotonic() - started < 5


def test_one_pages_hostile_json_fails_alone():
    depth = 100_000
    page = '<script type="application/ld+json">' + "[" * depth + "]" * depth + "</script>"
    assert pricewatch.read_markup(page) == {}
    nested = '{"a":' * 2000 + "1" + "}" * 2000
    pricewatch.read_markup(f'<script type="application/ld+json">{nested}</script>')


# ── where a fetch may go ─────────────────────────────────────────────────

@pytest.mark.parametrize("url", ["http://100.100.100.200/latest/meta-data/", "http://100.64.0.1/", "http://100.127.255.254/"])
def test_the_shared_address_space_is_the_readers_own_network(url):
    assert egress.reason_to_refuse(url)


def test_a_redirect_to_this_machine_is_refused_where_a_public_page_is_followed():
    handler = egress._RefuseUnsafeRedirects()
    request = urllib.request.Request("http://93.184.216.34/start")
    with pytest.raises(urllib.error.URLError):
        handler.redirect_request(request, None, 302, "Found", {}, "http://127.0.0.1:8787/api/settings")
    with pytest.raises(urllib.error.URLError):
        handler.redirect_request(request, None, 302, "Found", {}, "/../../x".replace("/../../x", "//localhost/x"))
    followed = handler.redirect_request(request, None, 302, "Found", {}, "http://93.184.216.35/next")
    assert followed is not None and followed.full_url == "http://93.184.216.35/next"


# ── a restore keeps the work it replaces ─────────────────────────────────

def test_each_restore_keeps_the_state_just_before_it(tmp_path):
    settings = Settings(store_path=tmp_path / "knowledge.sqlite", app_state_path=tmp_path / "app.sqlite")
    connect(settings.store_path).close()

    def titles(path):
        conn = state.connect(path)
        try:
            return sorted(t["title"] for t in state.chat_threads(conn))
        finally:
            conn.close()

    def add(title):
        conn = state.connect(settings.app_state_path)
        state.create_chat_thread(conn, title)
        conn.close()

    add("old")
    snapshot = backups.export(settings)
    add("kept-before-first-restore")
    assert backups.stage(settings, snapshot)["restart_required"] and backups.apply_pending(settings)
    add("work-done-after-restore-1")
    assert backups.stage(settings, snapshot)["restart_required"] and backups.apply_pending(settings)
    assert "work-done-after-restore-1" in titles(tmp_path / "app.sqlite.before-restore")
    assert "kept-before-first-restore" in titles(tmp_path / "app.sqlite.before-restore.prev")
    assert "work-done-after-restore-1" not in titles(settings.app_state_path)


# ── a model's malformed tool call is not a crash ─────────────────────────

@pytest.mark.parametrize("arguments", ["[1, 2]", "42", "null", '"text"', "{not json"])
def test_tool_call_arguments_that_are_not_an_object_ask_for_no_search(arguments):
    call = {"function": {"name": "search", "arguments": arguments}}
    assert chat.search_request(json.dumps(call)) == ""
    # The same arguments as a bare JSON value, not a string holding one.
    raw = '{"function": {"name": "search", "arguments": ' + arguments + "}}"
    assert chat.search_request(raw) == ""


# ── saved checks are searchable in the words they were written in ────────

@pytest.mark.parametrize("query", ["Türkiye", "garanti", "inç", 'Panel is 14"', "yıl", "Laptop"])
def test_a_saved_check_is_found_by_non_ascii_and_quoted_words(tmp_path, query):
    conn = state.connect(Path(tmp_path) / "app.sqlite")
    state.record_lookup(conn, source="compare", label="Laptop A", request={}, response={
        "claims": [{"text": "Ekran 15,6 inç, Türkiye garanti süresi 2 yıl"}, {"text": 'Panel is 14" class'}]})
    assert len(state.recent(conn, query=query)) == 1
