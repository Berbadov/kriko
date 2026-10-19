"""Outcomes a cooperative assistant owes the reader, without live providers."""

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import backups, chat, chatdata
from app.tests.test_chat_turn import Script
from app.turnusage import TurnUsage
from app.web import state
from app.web.app import create_app
from app.web.settings import Settings
from kriko.research import BudgetExceeded
from kriko.store.db import connect


def web_context(search=None, read=None):
    return chatdata.Context(web_search=search or (lambda q, n: [
        {"url": "https://maker.example/manual", "title": "Official manual"}]),
        web_read=read or (lambda u: "This model weighs 2 kilograms. The warranty lasts two years."))


def test_an_offer_to_start_is_repaired_into_actual_work():
    model = Script("I can help with that. Would you like me to get started?",
                   "Induction charging uses a changing magnetic field to induce current in a receiver coil.")
    out = chat.run_turn("Explain induction charging", ask=model, ctx=chatdata.Context())
    assert "receiver coil" in out["answer"]
    assert out["agent_calls"] == 2


def test_a_real_clarification_is_not_replaced_with_a_guess():
    model = Script("Which exact engine code is on the vehicle's identification plate?")
    out = chat.run_turn("I forgot the code we were discussing", ask=model, ctx=chatdata.Context())
    assert out["agent_calls"] == 1
    assert "Which exact engine code" in out["answer"]


def test_repeated_empty_offers_do_not_count_as_completion():
    with pytest.raises(RuntimeError, match="did not complete"):
        chat.run_turn("Explain induction charging", ctx=chatdata.Context(),
                      ask=Script("Would you like me to start?", "Would you like me to start?"))


def test_a_useful_answer_can_offer_an_optional_example_without_being_rejected():
    answer = "Induction charging transfers power through a changing magnetic field. Would you like an example?"
    out = chat.run_turn("Explain induction charging", ask=Script(answer), ctx=chatdata.Context())
    assert out["answer"] == answer
    assert out["agent_calls"] == 1


def test_a_search_request_after_reading_continues_and_delivers_the_result():
    queries = []
    def search(q, n):
        queries.append(q)
        return [{"url": "https://maker.example/manual", "title": "Manual"}]
    out = chat.run_turn("What is the latest model specification?", ctx=web_context(search),
                        ask=Script("SEARCH: model official manual", "It weighs 2 kilograms. [Manual](https://maker.example/manual)"))
    assert len(queries) == 2
    assert out["search_rounds"] == 2
    assert not out["answer"].startswith("SEARCH:")


def test_repeated_tool_requests_end_as_an_explicit_incomplete_run():
    with pytest.raises(RuntimeError, match="before the agent delivered"):
        chat.run_turn("What is the latest model specification?", ctx=web_context(),
                      ask=Script("SEARCH: model manual", "SEARCH: another manual"))


def test_both_reader_links_are_opened():
    opened = []
    def read(url):
        opened.append(url)
        return "A specification from this exact product."
    out = chat.run_turn("Compare https://maker.example/a and https://maker.example/b", ctx=web_context(read=read), ask=Script("Both pages list the specification."))
    assert set(opened) == {"https://maker.example/a", "https://maker.example/b"}
    assert out["activity"][0]["pages_read"] == 2


def test_failed_leading_results_are_replaced_by_readable_alternatives():
    opened = []
    def read(url):
        opened.append(url)
        return "This model weighs 2 kilograms." if url.endswith("/4") else ""
    ctx = web_context(search=lambda q, n: [{"url": f"https://maker.example/{i}"} for i in range(5)], read=read)
    out = chat.run_turn("Find the latest specification", ask=Script("It weighs 2 kilograms."), ctx=ctx)
    assert "https://maker.example/4" in opened
    assert out["activity"][0]["pages_read"] == 1


def test_retrieval_keeps_a_relevant_passage_far_beyond_the_old_prefix():
    long_page = "Navigation and unrelated products. " * 1800 + "\nThe spindle clearance is 74 mm for revision B only.\n"
    out = chatdata.run("web_search", web_context(read=lambda u: long_page), {"query": "spindle clearance revision B"})
    excerpt = out["rows"][0]["page_excerpt"]
    assert "74 mm for revision B only" in excerpt
    assert len(excerpt) <= chatdata.WEB_PAGE_EXCERPT_CAP


def test_older_user_constraints_and_recent_corrections_are_both_shown():
    history = [{"role": "reader", "text": "My budget is 800 EUR and I live in Germany."}]
    history += [{"role": "agent", "text": "Discussing another detail."}] * 12
    history += [{"role": "reader", "text": "Correction: the budget is now 650 EUR."}]
    prompt = chat.chat_brief("Which should I choose?", history)
    assert "800 EUR" in prompt and "650 EUR" in prompt and "Germany" in prompt
    assert "later corrections take precedence" in prompt


@pytest.mark.parametrize("message", ["Find a quiet air purifier", "Trouve-moi un purificateur silencieux", "Bana sessiz bir hava temizleyici bul"])
def test_discovery_requests_share_the_web_route(message):
    assert chat.route_message(message) == "web"


def test_an_unread_citation_triggers_repair_and_is_not_a_verified_source():
    model = Script("It weighs 900 kg. [Proof](https://never-read.example/proof)",
                   "It weighs 2 kilograms. [Manual](https://maker.example/manual)")
    out = chat.run_turn("What is the latest specification?", ask=model, ctx=web_context())
    assert "900" not in out["answer"]
    assert "https://never-read.example/proof" not in out["sources"]


def test_evidence_review_repairs_a_contradiction_even_when_the_url_is_real():
    def review(answer, pages):
        if "900" in answer:
            return {"supported": False, "issues": ["The source says 2 kilograms, not 900."]}
        return {"supported": True, "citations": [{"url": pages[0]["url"], "quote": "This model weighs 2 kilograms."}]}
    out = chat.run_turn("What is the latest specification?", ctx=web_context(),
                        ask=Script("It weighs 900 kg. [Manual](https://maker.example/manual)",
                                   "It weighs 2 kilograms. [Manual](https://maker.example/manual)"), verify_answer=review)
    assert "900" not in out["answer"]
    assert out["verification"]["claim_support"]["status"] == "supported"
    assert out["agent_calls"] <= chat.MAX_AGENT_CALLS


def test_a_review_cannot_approve_a_quote_that_was_not_on_its_page():
    out = chat.run_turn("What is the latest specification?", ctx=web_context(),
                        ask=Script("It weighs 900 kg.", "It weighs 900 kg."),
                        verify_answer=lambda a, p: {"supported": True, "citations": [{"url": p[0]["url"], "quote": "This model weighs 900 kg."}]})
    assert out["verification"]["claim_support"]["status"] == "unsupported"
    assert any(row["id"] == "evidence-warning" for row in out["activity"])


def test_cancellation_during_review_is_not_swallowed():
    from app.tests.test_chat_turn import Hooks
    hooks = Hooks()
    def review(_answer, _pages):
        hooks.stop_after = hooks.checks
        raise RuntimeError("request canceled")
    with pytest.raises(RuntimeError, match="cancelled"):
        chat.run_turn("What is the latest specification?", ctx=web_context(),
                      ask=Script("It weighs 2 kilograms."), hooks=hooks, verify_answer=review)


def test_a_turn_budget_includes_all_measured_calls_and_unknowns_stay_unknown():
    meter = TurnUsage(budget=0.1)
    meter.record({"usd": 0.06, "tokens": 100})
    assert meter.parameters({})["budget_usd"] == pytest.approx(0.04)
    meter.record({"usd": None, "tokens": None})
    assert meter.snapshot()["spent_usd"] is None
    assert meter.snapshot()["usage"]["measured_usd"] == 0.06
    meter.record({"usd": 0.04, "tokens": 100})
    with pytest.raises(BudgetExceeded):
        meter.parameters({})


def test_startup_creates_a_missing_state_directory(tmp_path):
    app = create_app(Settings(store_path=tmp_path / "knowledge.sqlite", app_state_path=tmp_path / "new" / "state" / "app.sqlite", analysis_log_path=tmp_path / "analysis.jsonl"))
    try:
        assert app.state.settings.app_state_path.exists()
    finally:
        app.state.jobs.shutdown()


def test_replaying_a_logical_chat_send_creates_one_message_and_job(tmp_path, monkeypatch):
    settings = Settings(store_path=tmp_path / "knowledge.sqlite", app_state_path=tmp_path / "app.sqlite", analysis_log_path=tmp_path / "analysis.jsonl")
    app = create_app(settings)
    monkeypatch.setattr(app.state.jobs, "_pump", lambda: None)
    try:
        client = TestClient(app)
        tid = client.post("/api/chat/threads", json={}).json()["thread_id"]
        path = f"/api/chat/threads/{tid}/messages"
        body = {"text": "Explain this product", "client_request_id": "one-logical-send"}
        first, second = client.post(path, json=body), client.post(path, json=body)
        assert first.status_code == second.status_code == 200
        assert first.json() == second.json()
        assert len(client.get(path).json()["items"]) == 1
        assert client.post(path, json={**body, "text": "A different request"}).status_code == 409
    finally:
        app.state.jobs.shutdown()


@pytest.mark.parametrize("has_draft", [True, False])
def test_snapshot_restores_committed_wal_data_and_drafts_without_provider_keys(tmp_path, has_draft):
    settings = Settings(store_path=tmp_path / "knowledge.sqlite", app_state_path=tmp_path / "app.sqlite")
    store = connect(settings.store_path)
    store.close()
    conn = state.connect(settings.app_state_path)
    thread = state.create_chat_thread(conn, "Keep this conversation")
    draft = tmp_path / "drafts" / "example" / "pack.toml"
    if has_draft:
        draft.parent.mkdir(parents=True)
        draft.write_text('id="example"', encoding="utf-8")
    (tmp_path / "keys.env").write_text("secret=not-for-export", encoding="utf-8")
    raw = backups.export(settings)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        assert "keys.env" not in archive.namelist()
        assert ("drafts/example/pack.toml" in archive.namelist()) == has_draft
    later = tmp_path / "drafts" / "later" / "pack.toml"
    later.parent.mkdir(parents=True)
    later.write_text('id="later"', encoding="utf-8")
    if has_draft:
        draft.write_text('id="changed"', encoding="utf-8")
    state.delete_chat_thread(conn, thread["thread_id"])
    conn.close()
    assert backups.stage(settings, raw)["restart_required"]
    assert backups.apply_pending(settings)
    restored = state.connect(settings.app_state_path)
    try:
        assert state.get_chat_thread(restored, thread["thread_id"])["title"] == "Keep this conversation"
    finally:
        restored.close()
    assert (tmp_path / "app.sqlite.before-restore").exists()
    assert (tmp_path / "keys.env").read_text("utf-8") == "secret=not-for-export"
    assert not later.exists()
    assert draft.exists() == has_draft
    if has_draft:
        assert draft.read_text("utf-8") == 'id="example"'


def test_a_snapshot_cannot_write_paths_outside_the_data_directory(tmp_path):
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as archive:
        archive.writestr("snapshot.json", json.dumps({"format": 1}))
        archive.writestr("app.sqlite", b"bad database")
        archive.writestr("../../escape", b"bad")
    with pytest.raises(ValueError, match="supported Kriko snapshot"):
        backups.stage(Settings(app_state_path=tmp_path / "app.sqlite"), raw.getvalue())


def test_history_search_reaches_older_records_before_paging(tmp_path):
    settings = Settings(store_path=tmp_path / "knowledge.sqlite", app_state_path=tmp_path / "app.sqlite", analysis_log_path=tmp_path / "analysis.jsonl")
    app = create_app(settings)
    conn = state.connect(settings.app_state_path)
    try:
        conn.executemany("INSERT INTO lookups VALUES (?,?,?,?,?,?)", [
            (f"check-{i}", "2026-10-19T12:00:00Z", "test", "Needle product" if i == 0 else f"Other product {i}", "{}", "{}")
            for i in range(230)])
        conn.commit()
        page = TestClient(app).get("/api/history?limit=200&q=Needle").json()
        assert [row["lookup_id"] for row in page["items"]] == ["check-0"]
    finally:
        conn.close()
        app.state.jobs.shutdown()


def test_chat_accounts_for_answer_and_metadata_under_one_budget(tmp_path, monkeypatch):
    from app.web import tasks
    from app.web.jobs import Progress

    settings = Settings(store_path=tmp_path / "knowledge.sqlite", app_state_path=tmp_path / "app.sqlite", analysis_log_path=tmp_path / "analysis.jsonl")
    conn = state.connect(settings.app_state_path)
    thread = state.create_chat_thread(conn)
    job = state.create_job(conn, "chat_ask", {})
    calls = []
    def ask(_settings, params, _progress, _brief, **kwargs):
        calls.append(params)
        kwargs["on_usage"]({"usd": 0.06 if len(calls) == 1 else 0.04, "tokens": 100})
        return ("Induction charging transfers energy through a changing magnetic field."
                if len(calls) == 1 else '{"title":"Induction charging","followups":[],"memory":"Explain induction charging."}'), []
    monkeypatch.setattr(tasks, "_use_local_ask", lambda *a: False)
    monkeypatch.setattr(tasks, "_ask_about_checks", ask)
    try:
        result = tasks.chat_ask(settings, {"thread_id": thread["thread_id"], "text": "Explain induction charging", "budget_usd": 0.1}, Progress(job, conn))
        assert len(calls) == 2
        assert calls[1]["budget_usd"] == pytest.approx(0.04)
        assert result["spent_usd"] == pytest.approx(0.1)
        assert result["tokens"] == 200
        assert state.get_chat_thread(conn, thread["thread_id"])["memory"] == "Explain induction charging."
    finally:
        conn.close()


def test_a_lost_provider_response_preserves_an_unpriced_attempt(tmp_path, monkeypatch):
    from app.web import tasks
    from app.web.jobs import Progress

    settings = Settings(store_path=tmp_path / "knowledge.sqlite", app_state_path=tmp_path / "app.sqlite")
    conn = state.connect(settings.app_state_path)
    thread = state.create_chat_thread(conn)
    job = state.create_job(conn, "chat_ask", {})
    monkeypatch.setattr(tasks, "_use_local_ask", lambda *a: False)
    def lost(*a, **kw):
        raise RuntimeError("The provider response was lost.")
    monkeypatch.setattr(tasks, "_ask_about_checks", lost)
    try:
        with pytest.raises(RuntimeError, match="response was lost"):
            tasks.chat_ask(settings, {"thread_id": thread["thread_id"], "text": "Explain charging"}, Progress(job, conn))
        kept = state.partial_of(conn, job)
        assert kept["spent_usd"] is None
        assert kept["usage"]["calls"] == 1
        assert kept["usage"]["priced_calls"] == 0
    finally:
        conn.close()


def test_local_cumulative_usage_is_not_counted_twice(tmp_path, monkeypatch):
    from app.web import tasks
    from app.web.jobs import Progress

    settings = Settings(store_path=tmp_path / "knowledge.sqlite", app_state_path=tmp_path / "app.sqlite")
    conn = state.connect(settings.app_state_path)
    thread = state.create_chat_thread(conn)
    job = state.create_job(conn, "chat_ask", {})
    class Model:
        model = "test-local"
        tokens_used = 0
        usage_complete = True
        def __call__(self, prompt):
            if "Produce conversation metadata" in prompt:
                self.tokens_used += 20
                return '{"title":"Charging","followups":[]}'
            self.tokens_used += 100
            return "Charging transfers energy into a battery for later use."
    monkeypatch.setattr(tasks, "_use_local_ask", lambda *a: True)
    monkeypatch.setattr(tasks, "_local_structured_completer", lambda *a: Model())
    try:
        out = tasks.chat_ask(settings, {"thread_id": thread["thread_id"], "text": "Explain charging"}, Progress(job, conn))
        assert out["tokens"] == 120
    finally:
        conn.close()


def test_public_pdf_manuals_are_read_with_page_references(monkeypatch):
    from email.message import Message
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    from app import chatweb

    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 200 Td (Spindle clearance: 74 mm.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    class Response(io.BytesIO):
        headers = Message()
        headers["Content-Type"] = "application/pdf"
        def getcode(self): return 200
    monkeypatch.setattr(chatweb, "_public_url", lambda url: url)
    monkeypatch.setattr(chatweb.network, "urlopen", lambda *a, **kw: Response(output.getvalue()))
    found = chatweb.reader()("https://maker.example/manual.pdf")
    assert "Page 1" in found.text and "74 mm" in found.text
