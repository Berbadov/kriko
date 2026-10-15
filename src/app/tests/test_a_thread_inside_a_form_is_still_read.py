"""A forum thread wrapped in a `<form>` is still a thread.

Invision, phpBB, XenForo and vBulletin put the whole topic inside a form for
their moderation tools. The reader dropped every `<form>` block, so the post
(172 KB of it on one Unraid thread titled "world of pain, stay away from
these") came out as 447 characters of menus. The desktop build has no
`trafilatura`, so this fallback is what every reader's app runs.
"""

import sys

import pytest

from app.providers import fetch


@pytest.fixture(autouse=True)
def the_shipped_extractor(monkeypatch):
    """No `trafilatura`, as in the desktop build: the stdlib path is under test."""
    monkeypatch.setitem(sys.modules, "trafilatura", None)

THREAD = """<html><head><title>Warning: Drive world of pain - Forum</title></head><body>
<header>Site header</header><nav>Home Forums</nav>
<main><form action="/topic/1/?csrfKey=abc" method="post">
<article><p>Posting this here in case anyone else runs into these issues, so it will save some time.
After four months the drive reported uncorrectable errors and then disappeared from the system. A firmware update did not help.</p></article>
<select name="moderation"><option>Delete</option></select><button>Go</button>
<input type="hidden" name="csrfKey" value="abc" />
</form></main><footer>Footer</footer></body></html>"""


def test_a_post_inside_a_form_is_kept():
    text = fetch.to_text(THREAD)
    assert "uncorrectable errors" in text
    assert "firmware update did not help" in text


def test_the_form_controls_and_page_furniture_still_go():
    text = fetch.to_text(THREAD)
    assert "Delete" not in text and "Site header" not in text and "Footer" not in text
