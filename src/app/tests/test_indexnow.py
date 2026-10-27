"""The IndexNow submission names exactly what the site publishes, under the key the site proves it holds."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "site" / "tools" / "indexnow.py"
KEY = "0123456789abcdef0123456789abcdef"


def _load():
    spec = importlib.util.spec_from_file_location("indexnow", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _site(tmp_path, key_text=KEY):
    (tmp_path / f"{KEY}.txt").write_text(key_text, encoding="utf-8")
    (tmp_path / "sitemap.xml").write_text("<urlset><url><loc>https://kriko.cc/</loc></url></urlset>", encoding="utf-8")
    (tmp_path / "sitemap-problems.xml").write_text(
        "<urlset><url><loc>https://kriko.cc/problems/</loc></url><url><loc>https://kriko.cc/</loc></url></urlset>", encoding="utf-8")
    return tmp_path


def test_the_request_lists_each_published_address_once_and_says_where_the_key_can_be_checked(tmp_path):
    (body,) = _load().requests(_site(tmp_path))
    assert body["urlList"] == ["https://kriko.cc/", "https://kriko.cc/problems/"]
    assert body["key"] == KEY and body["keyLocation"] == f"https://kriko.cc/{KEY}.txt" and body["host"] == "kriko.cc"


def test_a_long_list_is_sent_in_batches_the_protocol_accepts(tmp_path, monkeypatch):
    module = _load()
    monkeypatch.setattr(module, "BATCH", 2)
    site = _site(tmp_path)
    (site / "sitemap.xml").write_text("".join(f"<loc>https://kriko.cc/{n}/</loc>" for n in range(5)), encoding="utf-8")
    assert [len(body["urlList"]) for body in module.requests(site)] == [2, 2, 2, 1]


def test_a_key_file_that_does_not_hold_its_own_name_is_not_a_key(tmp_path):
    with pytest.raises(SystemExit):
        _load().requests(_site(tmp_path, key_text="not-the-key"))


def test_the_key_file_the_repository_ships_is_one_the_tool_accepts():
    site = SCRIPT.parents[1]
    module = _load()
    assert (site / f"{module.find_key(site)}.txt").is_file()
