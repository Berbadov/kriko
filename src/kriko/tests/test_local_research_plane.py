"""The local plane's two guarantees, and the machinery they rest on.

The reader's constraint, verbatim: do not trust the built-in packages, they
are mock examples. So every test builds its own catalog, its own sockets and
its own documents — nothing here reads a shipped pack, and the plane is only
ever exercised against data a test invented.

Three properties, in order of importance:

  1. **No false merges.** `M271.860` never resolves to a catalog holding
     `M271.861`, however close the letters are. A one-integer difference is
     the most convincing wrong thing a code matcher can do.
  2. **Fail fast.** A blocked source is rotated past, never waited on, and
     politeness budgets hold regardless of how many queries arrive.
  3. **Nothing invented.** A completion that emits a code the pack never
     catalogued, or a quote the page never contained, contributes nothing.
"""

import time

import pytest

from kriko.research.base import Document, Fetched, ResearchTask
from kriko.research.codes import (CANDIDATES, EXACT, NO_MATCH, extract_codes, normalize, resolve)
from kriko.research.local import LocalPlane
from kriko.research.politeness import (PolitenessScheduler, looks_blocked)


def task(**over):
    base = dict(
        subject_id="s1", subject_label="Widget MK2", subject_kind="widget",
        pack_id="p1", queries=["{label} common problems"],
        search_names=("Widget MK2",),
    )
    base.update(over)
    return ResearchTask(**base)


DOC_TEXT = (
    "The Widget MK2 pump, code WDG-860, fails early. "
    "Owner reports: the pump seized at 40,000 units without warning."
)
DOC = Document(url="https://example.test/wdg", text=DOC_TEXT)


# ---------------------------------------------------------------- codes


class TestNormalize:
    def test_punctuation_and_case_fold_away(self):
        assert normalize("wdg-860") == normalize("WDG 860")
        assert normalize("WDG_860") == "wdg860"

    def test_unicode_digits_fold_to_ascii(self):
        assert normalize("ＷＤＧ８６０") == "wdg860"
        assert normalize("WDG١٦٠") == "wdg160"

    def test_empty_and_noise(self):
        assert normalize("") == ""
        assert normalize("---") == ""


class TestResolveNoFalseMerges:
    CATALOG = ("M271.860", "M271.861", "WDG-860", "BME680")

    def test_exact_despite_spelling_noise(self):
        out = resolve("m 271.860", self.CATALOG)
        assert out.outcome == EXACT and out.code == "M271.860"

    def test_one_integer_off_is_never_a_match(self):
        out = resolve("M271.862", self.CATALOG)
        assert out.outcome == NO_MATCH and not out.candidates

    def test_adjacent_digits_never_even_offered_as_candidates(self):
        for wild in ("M271.8610", "M271.8", "M271.8600", "M271.869"):
            out = resolve(wild, self.CATALOG)
            assert out.outcome == NO_MATCH, wild

    def test_digit_core_rule_holds_across_spellings(self):
        assert resolve("wdg-860", self.CATALOG).code == "WDG-860"
        out = resolve("BME-680", self.CATALOG)
        assert out.outcome == EXACT and out.code == "BME680"

    def test_letters_judged_loosely_when_digits_agree(self):
        out = resolve("WDX860", self.CATALOG)
        assert out.outcome == CANDIDATES
        assert out.candidates[0][1] == "WDG-860"
        assert out.is_exact is False

    def test_new_code_is_no_match_not_an_error(self):
        out = resolve("XYZ999", self.CATALOG)
        assert out.outcome == NO_MATCH

    def test_normalized_catalog_can_be_precomputed(self):
        pre = {normalize(c): c for c in self.CATALOG}
        a = resolve("M271.860", self.CATALOG)
        b = resolve("M271.860", normalized_known=pre)
        assert a == b


class TestExtractCodes:
    def test_finds_catalogued_spelling_in_prose(self):
        got = extract_codes("pages mention WDG-860 and junk", ("WDG-860",))
        assert got == ("WDG-860",)

    def test_ignores_words_without_digits(self):
        assert extract_codes("ABC and XYZ only", ("WDG-860",)) == ()

    def test_ignores_unknown_digit_cores(self):
        assert extract_codes("failure of WDG-861 here", ("WDG-860",)) == ()


# ---------------------------------------------------------- politeness


class TestBlockedDetection:
    def test_forbidden_statuses_are_blocks(self):
        assert looks_blocked(403) and looks_blocked(429)

    def test_server_errors_are_not_blocks(self):
        assert not looks_blocked(503)

    def test_marker_words_in_the_head_are_blocks(self):
        assert looks_blocked(200, "<html>please complete the CAPTCHA</html>")
        assert looks_blocked(200, "Access Denied — attention required")

    def test_marker_beyond_head_is_not_a_block(self):
        body = "x" * 4096 + " captcha somewhere in the footer"
        assert not looks_blocked(200, body)


class TestScheduler:
    def make(self, **over):
        cfg = {"a": 0.0, "b": 0.0, "c": 0.0}
        cfg.update(over)
        scheduler_kwargs = {
            key: cfg.pop(key) for key in ("max_in_flight", "cooldown")
            if key in cfg
        }
        return PolitenessScheduler(cfg, **scheduler_kwargs)

    def test_blocks_burst_then_releases(self):
        s = self.make(a=5.0)
        first = s.acquire()
        assert first[0] == "a" and first[1] == 0.0
        second = s.acquire()
        assert second[0] != "a"
        s.release()
        s.release()
        assert s._in_flight == 0

    def test_blocked_source_is_rotated_past_not_waited_on(self):
        s = self.make()
        name, _ = s.acquire()
        s.release()
        s.report(name, blocked=True)
        assert s.is_hot(name)
        nxt, delay = s.acquire()
        s.release()
        assert nxt != name
        assert delay <= 1.0

    def test_global_in_flight_cap(self):
        s = self.make(max_in_flight=1)
        s.acquire()
        try:
            name, _ = s.acquire()
            assert name == ""
        finally:
            s.release()

    def test_cooldown_expires(self):
        s = self.make(cooldown=0.05)
        name, _ = s.acquire()
        s.release()
        s.report(name, blocked=True)
        assert s.is_hot(name)
        time.sleep(0.06)
        assert not s.is_hot(name)
        back, delay = s.acquire()
        s.release()
        assert back != "" and delay == 0.0

    def test_preferred_is_a_hint_not_a_promise(self):
        s = self.make()
        s.acquire()
        s.release()
        s.report("a", blocked=True)
        name, _ = s.acquire(preferred="a")
        s.release()
        assert name != "a"

    def test_requires_sources(self):
        with pytest.raises(ValueError):
            PolitenessScheduler({})

    def test_request_interval_is_enforced(self):
        s = self.make(a=0.2, b=99.0)
        s.acquire()
        s.release()
        s.report("a", blocked=True)
        name, delay = s.acquire()
        s.release()
        assert name == "b" or delay > 0


# ------------------------------------------------------------ the plane


def finding_json(url=DOC.url, quote=None, title="Pump fails early",
                 body="The pump fails early and costs a lot to find out."):
    return [{
        "source_url": url,
        "title": title,
        "domain": "fuel",
        "severity": "high",
        "quote": quote or "the pump seized at 40,000 units without warning",
        "body": body,
        "advice": "Ask for service records.",
    }]


class RecordingComplete:
    """A completion socket that replays scripted replies."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts: list[str] = []
        self.tokens_used = 0

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if not self.replies:
            return "[]"
        return self.replies.pop(0)


class TestLocalPlaneGrounding:
    def make(self, complete, codes=()):
        return LocalPlane(search=None, fetch=None, complete=complete,
                          codes=codes)

    def test_grounded_finding_survives(self):
        complete = RecordingComplete([__import__("json").dumps(
            finding_json())])
        plane = self.make(complete)
        found = plane.extract(task(), DOC)
        assert len(found) == 1
        assert found[0].severity == "high"
        assert found[0].source_url == DOC.url

    def test_invented_quote_is_dropped(self):
        complete = RecordingComplete([__import__("json").dumps(
            finding_json(quote="this sentence is not in the document"))])
        plane = self.make(complete)
        assert plane.extract(task(), DOC) == []

    def test_wrong_url_is_dropped(self):
        complete = RecordingComplete([__import__("json").dumps(
            finding_json(url="https://other.test/x"))])
        plane = self.make(complete)
        assert plane.extract(task(), DOC) == []

    def test_empty_and_garbage_replies_are_misses(self):
        for reply in ("", "not json at all", '{"a": 1}'):
            assert self.make(RecordingComplete([reply])).extract(
                task(), DOC) == []

    def test_fenced_json_is_accepted(self):
        payload = __import__("json").dumps(finding_json())
        complete = RecordingComplete(["```json\n" + payload + "\n```"])
        assert len(self.make(complete).extract(task(), DOC)) == 1

    def test_single_document_allows_missing_url(self):
        payload = [{k: v for k, v in finding_json()[0].items()
                    if k != "source_url"}]
        complete = RecordingComplete([__import__("json").dumps(payload)])
        assert len(self.make(complete).extract(task(), DOC)) == 1


class TestLocalPlaneCodeGate:
    QUOTE = "the pump seized at 40,000 units without warning"

    def test_catalogued_code_in_title_passes(self):
        payload = __import__("json").dumps(finding_json(
            title="WDG-860 pump fails early"))
        complete = RecordingComplete([payload])
        plane = LocalPlane(search=None, fetch=None, complete=complete,
                           codes=("WDG-860", "WDG-861"))
        assert len(plane.extract(task(), DOC)) == 1

    def test_invented_code_is_dropped(self):
        payload = __import__("json").dumps(finding_json(
            title="WDG-862 pump fails early"))
        complete = RecordingComplete([payload])
        plane = LocalPlane(search=None, fetch=None, complete=complete,
                           codes=("WDG-860",))
        assert plane.extract(task(), DOC) == []

    def test_one_integer_off_is_dropped_even_with_a_sibling(self):
        payload = __import__("json").dumps(finding_json(
            title="WDG-861 pump fails early"))
        complete = RecordingComplete([payload])
        plane = LocalPlane(search=None, fetch=None, complete=complete,
                           codes=("WDG-860",))
        assert plane.extract(task(), DOC) == []

    def test_no_codes_declared_means_no_gate(self):
        payload = __import__("json").dumps(finding_json(
            title="WDG-999 pump fails early"))
        complete = RecordingComplete([payload])
        plane = LocalPlane(search=None, fetch=None, complete=complete,
                           codes=())
        assert len(plane.extract(task(), DOC)) == 1

    def test_gate_reads_codes_from_the_tasks_own_identity(self):
        payload = __import__("json").dumps(finding_json(
            title="WDG-860 pump fails early"))
        complete = RecordingComplete([payload])
        plane = LocalPlane(search=None, fetch=None, complete=complete,
                           codes=())
        own = task(identity={"catalog_code": "WDG-860"},
                   attribution_aliases=("WDG-860", "WDG-861"))
        assert len(plane.extract(own, DOC)) == 1

    def test_identity_codes_refuse_an_invented_sibling(self):
        payload = __import__("json").dumps(finding_json(
            title="WDG-862 pump fails early"))
        complete = RecordingComplete([payload])
        plane = LocalPlane(search=None, fetch=None, complete=complete,
                           codes=())
        own = task(identity={"catalog_code": "WDG-860"})
        assert plane.extract(own, DOC) == []


class TestLocalPlaneGather:
    def test_gather_walks_queries_and_dedupes(self):
        hits = [{"url": "https://a.test/1", "title": "t", "site": "a"},
                {"url": "https://b.test/2", "title": "t", "site": "b"}]

        def search(query, limit):
            return hits if "common problems" in query else []

        def fetch(url):
            return Fetched(text="page body about failures.", published_at="")

        plane = LocalPlane(search=search, fetch=fetch, complete=RecordingComplete([]))
        docs = plane.gather(task(max_documents=2))
        assert [d.url for d in docs] == ["https://a.test/1", "https://b.test/2"]

    def test_gather_stops_at_max_documents(self):
        def search(query, limit):
            return [{"url": f"https://x.test/{i}", "title": "t", "site": "x"}
                    for i in range(5)]

        def fetch(url):
            return "body text"

        plane = LocalPlane(search=search, fetch=fetch, complete=RecordingComplete([]))
        assert len(plane.gather(task(max_documents=3))) == 3

    def test_unreadable_pages_are_misses(self):
        def search(query, limit):
            return [{"url": "https://a.test/1", "title": "t", "site": "a"}]

        def fetch(url):
            return ""

        plane = LocalPlane(search=search, fetch=fetch, complete=RecordingComplete([]))
        assert plane.gather(task()) == []


class TestSocketShape:
    def test_plane_name_and_cost_basis(self):
        assert LocalPlane.name == "local"
        assert LocalPlane.cost_basis == "self_hosted"

    def test_get_researcher_knows_local(self):
        from kriko.research import get_researcher
        plane = get_researcher({"backend": "local"}, search=None, fetch=None,
                               complete=lambda p: "[]")
        assert plane.name == "local"

    def test_get_researcher_rejects_unknown(self):
        from kriko.research import get_researcher
        with pytest.raises(ValueError):
            get_researcher({"backend": "paid-with-money"})

    def test_spent_calls_counted(self):
        complete = RecordingComplete([__import__("json").dumps(
            finding_json())])
        plane = LocalPlane(search=None, fetch=None, complete=complete)
        plane.extract(task(), DOC)
        assert plane.spent_calls == 1
