"""_select_capped — keep Tier A/B, trim Tier C YouTube first."""

from knowledge.auto import _select_capped


def _page(tier, n):
    return {"tier": tier, "url": f"https://{tier.lower()}{n}", "site_or_channel": "x", "notes": ""}


def _vids(n):
    return [{"id": f"v{i}"} for i in range(n)]


def test_cap_keeps_higher_tiers_first():
    pages = [_page("C", 1), _page("A", 1), _page("C", 2), _page("B", 1)]
    kept_pages, kept_vids = _select_capped(pages, _vids(5), cap=3)
    tiers = [p["tier"] for p in kept_pages]
    assert tiers == ["A", "B", "C"]      # ordered by trust
    assert kept_vids == []                # cap filled by pages — YouTube trimmed first


def test_videos_fill_remaining_budget():
    pages = [_page("A", 1), _page("B", 1)]
    kept_pages, kept_vids = _select_capped(pages, _vids(5), cap=4)
    assert len(kept_pages) == 2
    assert len(kept_vids) == 2            # 4 - 2 pages = 2 videos


def test_no_cap_breach_when_only_videos():
    kept_pages, kept_vids = _select_capped([], _vids(50), cap=10)
    assert kept_pages == []
    assert len(kept_vids) == 10


def test_cap_larger_than_available_keeps_all():
    pages = [_page("A", 1), _page("C", 1)]
    kept_pages, kept_vids = _select_capped(pages, _vids(2), cap=25)
    assert len(kept_pages) == 2
    assert len(kept_vids) == 2
