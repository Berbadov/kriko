from datetime import date, timedelta

from packs.cars.pipeline.sources import dates


def _html_with_meta(content: str) -> str:
    return (
        "<html><head>"
        f'<meta property="article:published_time" content="{content}">'
        "</head><body><p>" + ("word " * 60) + "</p></body></html>"
    )


def test_page_published_at_reads_real_metadata_date():
    html = _html_with_meta("2021-05-03T10:00:00Z")
    assert dates.page_published_at(html, source="https://x.test/a") == "2021-05-03"


def test_page_published_at_blank_when_no_date_anywhere():
    html = "<html><head><title>no date</title></head><body><p>" + (
        "word " * 60
    ) + "</p></body></html>"
    assert dates.page_published_at(html, source="https://x.test/b") == ""


def test_from_trafilatura_date_rejects_malformed_string():
    assert dates.from_trafilatura_date("not-a-date", source="x") == ""


def test_from_trafilatura_date_rejects_future_date():
    future = (date.today() + timedelta(days=30)).isoformat()
    assert dates.from_trafilatura_date(future, source="x") == ""


def test_from_trafilatura_date_rejects_absurdly_old_date():
    assert dates.from_trafilatura_date("1899-01-01", source="x") == ""


def test_from_trafilatura_date_accepts_todays_date():
    today = date.today().isoformat()
    assert dates.from_trafilatura_date(today, source="x") == today


def test_from_trafilatura_date_blank_input_is_blank_output():
    assert dates.from_trafilatura_date(None, source="x") == ""
    assert dates.from_trafilatura_date("", source="x") == ""


def test_from_yt_dlp_upload_date_normalizes_yyyymmdd():
    assert dates.from_yt_dlp_upload_date("20210503", source="x") == "2021-05-03"


def test_from_yt_dlp_upload_date_rejects_malformed():
    assert dates.from_yt_dlp_upload_date("not-a-date", source="x") == ""
    assert dates.from_yt_dlp_upload_date("2021-05-03", source="x") == ""  # wrong shape


def test_from_yt_dlp_upload_date_rejects_out_of_range():
    assert dates.from_yt_dlp_upload_date("19800101", source="x") == ""
    future = (date.today() + timedelta(days=10)).strftime("%Y%m%d")
    assert dates.from_yt_dlp_upload_date(future, source="x") == ""


def test_youtube_published_at_reads_info_dict():
    assert dates.youtube_published_at({"upload_date": "20200115"}, source="x") == "2020-01-15"
    assert dates.youtube_published_at({}, source="x") == ""
    assert dates.youtube_published_at(None, source="x") == ""
