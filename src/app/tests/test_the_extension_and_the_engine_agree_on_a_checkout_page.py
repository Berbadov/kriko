"""A cart page is known by the same words in the worker and in the engine.

The worker decides whether to look before paying (`CHECKOUT_PATH` in
`extension/background.js`); the engine decides what the look says
(`app/checkout.py`). A word added on one side only is a cart page one of them
never reacts to, which is a silent hole rather than a failure.
"""

import re
from pathlib import Path

from app import checkout

ROOT = Path(__file__).resolve().parents[3]


def words(source: str) -> set[str]:
    group = re.search(r"\(\?:((?:[a-z]+\|)+[a-z]+)\)\(\?:", source)
    assert group, "could not find the word list"
    return set(group.group(1).split("|"))


def test_the_worker_and_the_engine_name_a_cart_page_by_the_same_words():
    js = (ROOT / "extension" / "background.js").read_text(encoding="utf-8")
    declared = re.search(r"const CHECKOUT_PATH = /(.*?)/i;", js)
    assert declared, "the worker no longer declares CHECKOUT_PATH"
    assert words(declared.group(1)) == words(checkout.CHECKOUT_PATH.pattern)


def test_the_extension_manifest_asks_for_notifications_only_when_the_reader_does():
    import json

    manifest = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
    assert "notifications" not in manifest["permissions"]
    assert manifest["optional_permissions"] == ["notifications"]
