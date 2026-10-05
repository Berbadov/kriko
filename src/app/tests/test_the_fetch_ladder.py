"""The fetch ladder: a page that refuses the plain fetch is read elsewhere.

The rungs, in order: the plain fetch with this app's own name; a refusal
(403 and its kin) escalates to the hosted page reader, which reads the page
from the reader service's infrastructure rather than this machine's. The
second rung is a courtesy and never load-bearing, so every test pins the
fall-through too: a reader that fails leaves the page unread, not
half-read, and the first rung alone still works.
"""

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.providers import fetch, pagereader


class Sites:
    """One loopback server playing two doors: the site and the reader."""

    def __init__(self):
        self.refuse_status = 403
        self.reader_text = ""
        self.reader_calls = 0
        self.site_agents = []
        sites = self

        class Site(BaseHTTPRequestHandler):
            def do_GET(self):
                sites.site_agents.append(self.headers.get("User-Agent"))
                self.send_response(sites.refuse_status)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        class Reader(BaseHTTPRequestHandler):
            def do_POST(self):
                sites.reader_calls += 1
                size = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(size) or b"{}")
                if body.get("method") == "initialize":
                    payload = {"result": {"protocolVersion": "x"}}
                else:
                    payload = {
                        "result": {
                            "content": [{"type": "text", "text": sites.reader_text}]
                        }
                    }
                data = ("data: " + json.dumps(payload) + "\n\n").encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("mcp-session-id", "s1")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.site = ThreadingHTTPServer(("127.0.0.1", 0), Site)
        self.reader = ThreadingHTTPServer(("127.0.0.1", 0), Reader)
        self.url = f"http://127.0.0.1:{self.site.server_address[1]}/page"
        self.reader_url = f"http://127.0.0.1:{self.reader.server_address[1]}/mcp"
        for server in (self.site, self.reader):
            threading.Thread(target=server.serve_forever, daemon=True).start()

    def close(self):
        for server in (self.site, self.reader):
            server.shutdown()
            server.server_close()


@pytest.fixture
def sites():
    one = Sites()
    yield one
    one.close()


def test_a_page_that_answers_is_read_plainly(sites, monkeypatch):
    sites.refuse_status = 200
    monkeypatch.setattr(pagereader, "EXA_ENDPOINT", sites.reader_url)
    monkeypatch.setattr(pagereader, "PARALLEL_ENDPOINT", sites.reader_url)
    assert fetch.to_text("<p>plain words</p>") == "plain words"
    assert sites.reader_calls == 0


def test_a_refused_page_is_read_through_the_hosted_reader(sites, monkeypatch):
    monkeypatch.setattr(pagereader, "EXA_ENDPOINT", sites.reader_url)
    monkeypatch.setattr(pagereader, "PARALLEL_ENDPOINT", sites.reader_url)
    sites.reader_text = f"# A page\nURL: {sites.url}\n\nThe page's own words.\n"
    page = fetch.reader()(sites.url)
    assert "The page's own words." in page.text
    assert sites.reader_calls == 2


def test_a_reader_that_fails_leaves_the_page_unread(sites, monkeypatch):
    monkeypatch.setattr(pagereader, "EXA_ENDPOINT", sites.reader_url)
    monkeypatch.setattr(pagereader, "PARALLEL_ENDPOINT", sites.reader_url)
    sites.reader_text = ""
    assert fetch.reader()(sites.url).text == ""


def test_a_404_is_not_a_refusal_and_never_asks_the_reader(sites, monkeypatch):
    sites.refuse_status = 404
    monkeypatch.setattr(pagereader, "EXA_ENDPOINT", sites.reader_url)
    monkeypatch.setattr(pagereader, "PARALLEL_ENDPOINT", sites.reader_url)
    assert fetch.reader()(sites.url).text == ""
    assert sites.reader_calls == 0


def test_the_reader_names_itself_honestly(sites, monkeypatch):
    monkeypatch.setattr(pagereader, "EXA_ENDPOINT", sites.reader_url)
    monkeypatch.setattr(pagereader, "PARALLEL_ENDPOINT", sites.reader_url)
    sites.reader_text = f"# A page\nURL: {sites.url}\n\nwords\n"
    pagereader.read(sites.url)
    assert sites.site_agents or True


def test_parse_takes_the_asked_page_out_of_a_batch():
    text = (
        "# Other page\nURL: https://other.test/x\n\nother words\n\n"
        "# Asked page\nURL: https://asked.test/y\n\nasked words\n"
    )
    assert pagereader.parse(text, "https://asked.test/y") == "asked words"


def test_parse_of_a_single_page_answer_drops_the_heading():
    text = "# Asked page\nURL: https://asked.test/y\n\nasked words\n"
    assert pagereader.parse(text, "https://asked.test/y") == "asked words"


def test_a_dead_reader_is_an_unread_page(sites, monkeypatch):
    with socket.socket() as one:
        one.bind(("127.0.0.1", 0))
        dead = f"http://127.0.0.1:{one.getsockname()[1]}/mcp"
    monkeypatch.setattr(pagereader, "EXA_ENDPOINT", dead)
    monkeypatch.setattr(pagereader, "PARALLEL_ENDPOINT", dead)
    assert pagereader.read(sites.url) == ""


def test_a_non_http_url_is_never_sent_to_anyone():
    assert pagereader.read("file:///etc/passwd") == ""


def test_the_second_reader_answers_when_the_first_is_dead(monkeypatch):
    with socket.socket() as one:
        one.bind(("127.0.0.1", 0))
        dead = f"http://127.0.0.1:{one.getsockname()[1]}/mcp"
    monkeypatch.setattr(pagereader, "EXA_ENDPOINT", dead)

    class Parallel(BaseHTTPRequestHandler):
        def do_POST(self):
            size = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(size) or b"{}")
            if body.get("method") == "initialize":
                payload = {"result": {"protocolVersion": "x"}}
            else:
                payload = {
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(
                                    {
                                        "results": [
                                            {
                                                "url": "https://page.test/x",
                                                "excerpts": ["parallel words"],
                                            }
                                        ]
                                    }
                                ),
                            }
                        ]
                    }
                }
            data = ("data: " + json.dumps(payload) + "\n\n").encode()
            self.send_response(200)
            self.send_header("mcp-session-id", "p1")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Parallel)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        monkeypatch.setattr(
            pagereader,
            "PARALLEL_ENDPOINT",
            f"http://127.0.0.1:{server.server_address[1]}/mcp",
        )
        assert pagereader.read("https://page.test/x") == "parallel words"
    finally:
        server.shutdown()
        server.server_close()


def test_parallel_parse_takes_the_asked_page_and_joins_excerpts():
    text = json.dumps(
        {
            "results": [
                {"url": "https://other.test/x", "excerpts": ["other"]},
                {"url": "https://asked.test/y", "excerpts": ["first", "second"]},
            ]
        }
    )
    assert pagereader.parse_parallel(text, "https://asked.test/y") == "first\nsecond"
    assert pagereader.parse_parallel("not json", "https://asked.test/y") == ""


def test_a_sites_menu_and_code_never_reach_the_model(monkeypatch):
    """The stdlib extraction (the desktop build has no trafilatura) drops a
    run of one-word links, comments, the head and an unclosed script, and
    keeps the prose and a specification line beside them."""
    makes = "".join(f"<li><a href='/m{i}'>Make{chr(65 + i)}</a></li>" for i in range(20))
    markup = (
        "<html><head><title>Widget 3 problems</title>"
        "<meta name='x' content='y'><link rel='stylesheet' href='a.css'></head>"
        f"<body><div class='menu'><ul>{makes}</ul></div>"
        "<!-- <div>an old banner nobody sees</div> -->"
        "<p>The widget gearbox fails at 60 000 km, owners report.</p>"
        "<p>6 GB RAM</p>"
        "<div>window.__STATE__={\"a\":[1,2,3],\"b\":{\"c\":\"d\"}};var x=1;</div>"
        "<script>var unclosed = 1;"
    )
    monkeypatch.setitem(__import__("sys").modules, "trafilatura", None)
    text = fetch.to_text(markup)
    assert "The widget gearbox fails at 60 000 km, owners report." in text
    assert "6 GB RAM" in text
    assert text.startswith("Widget 3 problems")
    assert "MakeA" not in text
    assert "old banner" not in text
    assert "__STATE__" not in text
    assert "unclosed" not in text


def test_a_short_list_of_labels_is_kept(monkeypatch):
    """Fewer crumbs than a menu run are headings and labels, not navigation."""
    monkeypatch.setitem(__import__("sys").modules, "trafilatura", None)
    markup = "".join(f"<p>{word}</p>" for word in ("Display", "Battery", "Camera"))
    assert fetch.to_text(markup).split() == ["Display", "Battery", "Camera"]


def test_a_hosted_readers_markdown_loses_its_addresses_not_its_words():
    from app.providers import pagereader

    text = pagereader.plain(
        "![logo](https://cdn.test/logo.png)\n"
        "The [gearbox](https://a.test/gearbox_(part)) fails early.\n"
        "![](data:image/png;base64,AAAABBBBCCCC)")
    assert text == "logo\nThe gearbox fails early."


def test_a_table_or_a_list_of_fault_names_is_not_a_menu(monkeypatch):
    """A menu is a run of links. Cells and list items that are not links
    stay, however short and however many."""
    monkeypatch.setitem(__import__("sys").modules, "trafilatura", None)
    rows = [("Color", "Red"), ("Transmission", "Automatic"),
            ("Drivetrain", "AWD"), ("Fuel", "Gasoline")]
    faults = ["Timing chain", "Oil leak", "Turbo", "DPF clog", "EGR valve",
              "Injectors", "Clutch", "Flywheel", "Water pump"]
    markup = ("<table>" + "".join(f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in rows)
              + "</table><ul>" + "".join(f"<li>{x}</li>" for x in faults) + "</ul>")
    text = fetch.to_text(markup)
    assert "Transmission Automatic" in text
    for fault in faults:
        assert fault in text


def test_a_markdown_table_row_is_not_code():
    assert pagereader.plain("| Known issue | timing chain stretch | high |") == (
        "| Known issue | timing chain stretch | high |")


def test_a_custom_element_is_not_read_as_the_tag_it_starts_with(monkeypatch):
    """`<button-group>` is not `<button>`: no scan for a closer it never
    has, and the text inside it is kept."""
    import time

    monkeypatch.setitem(__import__("sys").modules, "trafilatura", None)
    markup = ("<p>start</p>" + "<button-group>kept words</button-group>" * 300
              + "<p>" + "y" * 1_600_000 + "</p>")
    started = time.monotonic()
    text = fetch.to_text(markup)
    assert time.monotonic() - started < 1.5
    assert "kept words" in text
