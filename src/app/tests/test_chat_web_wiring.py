"""Chat reuses configured search, keeps ordinary turns tool-less, and streams prose."""

from app import prefs
from app.web import state, tasks


class Hooks:
    def check(self):
        pass


def test_local_token_stream_is_accumulated_into_complete_chat_drafts():
    class Socket:
        def stream(self, prompt, on_text):
            for piece in ["Hello", " there", "."]:
                on_text(piece)
            return "Hello there."

    drafts = []
    assert tasks._stream_chat_completion(Socket(), "hello", drafts.append) == "Hello there."
    assert drafts == ["Hello", "Hello there", "Hello there."]


def test_free_chat_search_uses_saved_address_language_and_bounded_sockets(tmp_path, monkeypatch):
    from app import chatweb
    from app.providers import openserp

    conn = state.connect(tmp_path / "app.sqlite")
    try:
        prefs.write(conn, {prefs.LOCAL_SEARCH_URL: "http://127.0.0.1:7111",
                           prefs.LOCAL_SEARCH_LANGUAGE: "tr"})
        seen = {}

        def searcher(base, **kwargs):
            seen.update(base=base, **kwargs)
            return lambda query, limit: [{"url": "https://example.org", "title": query}]

        monkeypatch.setattr(openserp, "searcher", searcher)
        monkeypatch.setattr(chatweb, "reader", lambda **kwargs: seen.update(read=kwargs) or (lambda url: "text"))
        hooks = Hooks()
        search, read = tasks._chat_web_sources(conn, tmp_path / "app.sqlite", hooks)
        assert seen == {"base": "http://127.0.0.1:7111", "engine": "duckduckgo,bing,google",
                        "language": "tr", "timeout": 8.0, "mode": "any",
                        "read": {"timeout": 5.0}}
        assert search.check_cancelled == hooks.check
        assert search("a product", 3)[0]["title"] == "a product"
        assert read("https://example.org") == "text"
    finally:
        conn.close()


def test_chat_honours_an_explicit_hosted_search_choice(tmp_path, monkeypatch):
    from app import providers

    conn = state.connect(tmp_path / "app.sqlite")
    try:
        prefs.write(conn, {prefs.SEARCH: "tavily"})
        seen = []

        def selected(path, preferred):
            seen.append((path, preferred))
            return (lambda query, limit: []), "tavily"

        monkeypatch.setattr(providers, "_searcher", selected)
        tasks._chat_web_sources(conn, tmp_path / "app.sqlite", Hooks())
        assert seen == [(tmp_path / "app.sqlite", "tavily")]
    finally:
        conn.close()
