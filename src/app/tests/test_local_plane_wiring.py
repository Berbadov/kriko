"""The local plane, wired the way a run actually wires it.

These tests own no fake catalog and no shipped pack: the sockets are
invented here, the SERP adapter is exercised against a scripted local HTTP
server, and the provider factory is proven to produce a plane whose
provenance fields a run can record. Nothing touches the network beyond
127.0.0.1, and nothing reads a key.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.providers import local_researcher
from app.providers.openserp import LocalSearchError, searcher
from kriko.research.base import ResearchTask
from kriko.research.local import LocalPlane
from kriko.research.politeness import PolitenessScheduler


def task(**over):
    base = dict(
        subject_id="s1", subject_label="Widget MK2", subject_kind="widget",
        pack_id="p1", queries=["{label} common problems"],
        search_names=("Widget MK2",),
    )
    base.update(over)
    return ResearchTask(**base)


class TestOpenSERPAdapter:
    @pytest.fixture
    def serp(self):
        payloads = {}
        server = HTTPServer(("127.0.0.1", 0), _make_handler(payloads))
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        yield f"http://127.0.0.1:{port}", payloads
        server.shutdown()

    def test_translates_results_to_the_injected_shape(self, serp):
        base, payloads = serp
        payloads["reply"] = json.dumps({"results": [{
            "url": "https://a.test/x", "title": "t", "domain": "a.test",
        }]})
        search = searcher(base_url=base)
        hits = search("widget problems", 5)
        assert hits == [{"url": "https://a.test/x", "title": "t",
                         "site": "a.test"}]
        assert search.stats["queries"] == 1 and search.stats["hits"] == 1

    def test_domain_falls_back_to_the_urls_host(self, serp):
        base, payloads = serp
        payloads["reply"] = json.dumps({"results": [{
            "url": "https://b.test/y", "title": "t",
        }]})
        assert searcher(base_url=base)("q", 1)[0]["site"] == "b.test"

    def test_challenge_body_raises_so_the_plane_rotates(self, serp):
        base, payloads = serp
        payloads["reply"] = "<html>please complete the CAPTCHA</html>"
        with pytest.raises(LocalSearchError):
            searcher(base_url=base)("q", 1)

    def test_garbage_raises(self, serp):
        base, payloads = serp
        payloads["reply"] = "not json"
        with pytest.raises(LocalSearchError):
            searcher(base_url=base)("q", 1)

    def test_empty_results_are_a_miss_not_an_error(self, serp):
        base, payloads = serp
        payloads["reply"] = json.dumps({"results": []})
        assert searcher(base_url=base)("q", 1) == []


class TestLocalResearcherWiring:
    def test_factory_produces_a_local_plane(self):
        plane = local_researcher()
        assert isinstance(plane, LocalPlane)
        assert plane.name == "local"
        assert plane.cost_basis == "self_hosted"
        assert plane.model == "local"
        assert plane.search_provider.startswith("openserp:")

    def test_factory_accepts_a_scheduler_and_names(self):
        scheduler = PolitenessScheduler({"duckduckgo": 3.5})
        plane = local_researcher(scheduler=scheduler,
                                serving_name="qwen3-4b",
                                engine="duckduckgo")
        assert plane._scheduler is scheduler
        assert plane.model == "qwen3-4b"
        assert plane.search_provider == "openserp:duckduckgo"


class TestPlaneWithSchedulerEndToEnd:
    def test_blocked_search_rotates_and_the_run_continues(self):
        calls = []

        def search(query, limit):
            calls.append(query)
            raise LocalSearchError("the SERP answered with a challenge page")

        def fetch(url):
            return "body text"

        def complete(prompt):
            return json.dumps([{
                "source_url": "https://a.test/x",
                "title": "Pump fails early",
                "domain": "fuel", "severity": "high",
                "quote": "body text",
                "body": "Two plain sentences about what goes wrong.",
                "advice": "",
            }])

        scheduler = PolitenessScheduler({"duckduckgo": 0.0, "bing": 0.0})
        plane = LocalPlane(search=search, fetch=fetch, complete=complete,
                          scheduler=scheduler)
        assert plane.gather(task(max_documents=1)) == []
        assert scheduler.stats["blocked"] >= 1
        assert len(calls) >= 1

    def test_polite_gather_never_exceeds_one_query_per_source(self):
        queries = []

        def search(query, limit):
            queries.append(query)
            return [{"url": f"https://a.test/{len(queries)}",
                     "title": "t", "site": "a.test"}]

        def fetch(url):
            return "readable page text"

        scheduler = PolitenessScheduler({"duckduckgo": 0.0})
        plane = LocalPlane(search=search, fetch=fetch,
                           complete=lambda p: "[]",
                           scheduler=scheduler)
        own = task(max_documents=3,
                   queries=["{label} problems", "{label} failures"])
        docs = plane.gather(own)
        assert len(docs) == 2
        assert scheduler.stats["requests"] >= 2
        assert len(queries) == 2


def _make_handler(payloads):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = payloads.get("reply", "{}")
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    return Handler
