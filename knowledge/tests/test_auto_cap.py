"""_select_capped — pages fill the budget first, then YouTube."""

from knowledge.auto import _select_capped


def _page(n):
    return {"url": f"https://page{n}", "site_or_channel": "x", "notes": ""}


def _vids(n):
    return [{"id": f"v{i}"} for i in range(n)]


def test_cap_pages_before_videos():
    pages = [_page(i) for i in range(4)]
    kept_pages, kept_vids = _select_capped(pages, _vids(5), cap=3)
    assert len(kept_pages) == 3
    assert kept_vids == []              # cap filled by pages — YouTube trimmed first


def test_videos_fill_remaining_budget():
    pages = [_page(1), _page(2)]
    kept_pages, kept_vids = _select_capped(pages, _vids(5), cap=4)
    assert len(kept_pages) == 2
    assert len(kept_vids) == 2          # 4 - 2 pages = 2 videos


def test_no_cap_breach_when_only_videos():
    kept_pages, kept_vids = _select_capped([], _vids(50), cap=10)
    assert kept_pages == []
    assert len(kept_vids) == 10


def test_cap_larger_than_available_keeps_all():
    pages = [_page(1), _page(2)]
    kept_pages, kept_vids = _select_capped(pages, _vids(2), cap=25)
    assert len(kept_pages) == 2
    assert len(kept_vids) == 2
