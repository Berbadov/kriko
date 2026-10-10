"""Local Quick Look keeps source evidence and reports output failures."""

import json

from app import quicklook
from app.providers import local_agent, local_asker


def test_factory_accepts_the_hosted_search_setting():
    asker = local_asker(base_url="http://127.0.0.1:1", serving_name="test",
                        search_kind="exa")
    assert asker.parallel_search is True


def test_small_runtime_receives_a_bounded_prompt_and_grounded_answer():
    url = "https://example.org/report"
    quote = "The drive failed after one month."

    class Socket:
        max_tokens = 8192
        _schema = {}

        def context_tokens(self):
            return 4096

        def prompt_chars_allowed(self):
            return (4096 - self.max_tokens - 128) * 3

        def __call__(self, prompt):
            assert len(prompt) <= self.prompt_chars_allowed()
            if "risks" in self._schema.get("properties", {}):
                fields = self._schema["properties"]["risks"]["items"]["anyOf"][0]["properties"]
                assert fields["url"]["enum"] == [url]
                assert quote in fields["quote"]["enum"]
                assert fields["title"]["enum"] == [quote]
                assert fields["why"]["enum"] == [quote]
                assert quote in prompt
                return json.dumps({"risks": [{"title": "Drive failure",
                    "why": "An owner reported a failed drive.", "url": url,
                    "quote": quote, "severity": "medium"}], "specs": []})
            return '{"unsupported": [], "note": "checked"}'

    socket = Socket()
    asker = local_agent.LocalAsker(lambda _: '["Widget drive failures"]', socket,
        lambda *_: [{"url": url}],
        lambda _: "Navigation\n\n" * 1500 + quote,
        model="test", search_provider="stub")
    reply = asker.ask(quicklook.brief("Widget", compact=True))
    result = quicklook.parse(reply, asker.sources)
    assert result["risks"][0]["sources"][0]["grounded"]
    assert socket.max_tokens == 1024
    assert socket._schema == {}


def test_wrong_json_shape_is_repaired_once():
    replies = iter(['{"answer": "a drive failure"}',
                    '{"risks": [], "specs": []}',
                    '{"unsupported": [], "note": ""}'])
    prompts = []

    def complete(prompt):
        prompts.append(prompt)
        return next(replies)

    asker = local_agent.LocalAsker(lambda _: '["Widget failures"]', complete,
        lambda *_: [{"url": "https://example.org/report"}],
        lambda _: "The drive failed.", model="test", search_provider="stub")
    reply = asker.ask(quicklook.brief("Widget", compact=True))
    assert json.loads(reply) == {"risks": [], "specs": []}
    assert len(prompts) == 3


def test_empty_result_reports_the_actual_output_failure():
    invalid = "I found several issues but did not produce JSON."
    assert "unreadable" in quicklook.outcome(invalid, quicklook.parse(invalid))
    assert "cut off" in quicklook.outcome(invalid, quicklook.parse(invalid),
                                          finish_reason="length")
    empty = '{"risks": [], "specs": []}'
    assert "did not yield" in quicklook.outcome(empty, quicklook.parse(empty))


def test_unverified_claims_do_not_become_cards():
    reply = json.dumps({"risks": [{"title": "Failure", "url": "https://e.org",
                                   "quote": "an invented quote"}]})
    found = quicklook.parse(reply, {"https://e.org": "a different statement"})
    assert not found["risks"]
    assert "source checks" in quicklook.outcome(reply, found)


def test_specs_cannot_cite_an_address_that_was_never_read():
    reply = json.dumps({"specs": [{"name": "Weight", "value": "2 kg",
                                  "url": "https://misspelled.example/spec"}]})
    assert not quicklook.parse(reply, {"https://example.org/spec": "2 kg"})["specs"]


def test_planner_cannot_change_the_brand_and_model():
    product = "\u015e\u0131mart Katya \u00dc"
    queries = local_agent.plan.propose(quicklook.brief(product, compact=True),
        lambda _: '["another brand failures", "robot vacuum problems"]')
    assert all(product in query for query in queries)
