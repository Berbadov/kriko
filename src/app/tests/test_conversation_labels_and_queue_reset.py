"""Labels cannot overwrite names; completing a batch cannot delete queued work."""

import json
from types import SimpleNamespace

from app import chatmeta
from app.web import state


def test_completed_batch_preserves_results_and_other_work(tmp_path):
    conn = state.connect(tmp_path / "app.sqlite")
    try:
        done, _, _ = state.queue_product(conn, "https://shop.example/done", "Done")
        waiting, _, _ = state.queue_product(conn, "https://shop.example/wait", "Waiting")
        restarted, _, _ = state.queue_product(conn, "https://shop.example/restart", "Restarted")
        for item in (done, restarted):
            state.update_queued(conn, item["queue_id"], state="researching")
            state.update_queued(conn, item["queue_id"], state="done", lookup_id="saved-check")
        # Another window queues the product again before cleanup arrives.
        state.queue_product(conn, restarted["url"], restarted["name"])
        removed = state.complete_queue(conn, [done["queue_id"], waiting["queue_id"], restarted["queue_id"]])
        assert removed == [done["queue_id"]]
        assert {row["queue_id"] for row in state.research_queue(conn)} == {waiting["queue_id"], restarted["queue_id"]}
        archived = next(row for row in state.queue_history(conn) if row["queue_id"] == done["queue_id"])
        assert archived["state"] == "done" and archived["lookup_id"] == "saved-check"
        assert state.complete_queue(conn, removed) == []
    finally:
        conn.close()


def test_model_titles_preserve_custom_names_and_followups_survive_reload(tmp_path):
    path = tmp_path / "app.sqlite"
    conn = state.connect(path)
    first = state.create_chat_thread(conn)
    state.title_chat_thread(conn, first["thread_id"], "Which board fits this CPU?")
    assert state.name_chat_thread(conn, first["thread_id"], "CPU and motherboard fit", fallback="Which board fits this CPU?")
    custom = state.create_chat_thread(conn, "My custom title")
    assert not state.name_chat_thread(conn, custom["thread_id"], "New title", fallback="Question")
    state.add_chat_message(conn, first["thread_id"], role="agent", text="BIOS version is unknown.",
                           followups=["Which BIOS version supports this CPU?"])
    conn.close()
    conn = state.connect(path)
    try:
        assert state.get_chat_thread(conn, custom["thread_id"])["title"] == "My custom title"
        assert state.chat_messages(conn, first["thread_id"])[0]["followups"] == ["Which BIOS version supports this CPU?"]
    finally:
        conn.close()


def test_metadata_is_bounded_plain_text_and_does_not_trust_markup():
    parsed = chatmeta.parse('<think>private</think>```json\n' + json.dumps({
        "title": "Memory compatibility", "followups": ["What BIOS is required?", "What BIOS is required?", "<script>bad</script>", "https://example.com"]}) + '\n```')
    assert parsed == {"title": "Memory compatibility", "followups": ["What BIOS is required?"]}
    assert chatmeta.parse("not JSON") == {"title": "", "followups": []}


def test_chat_uses_selected_model_for_title_and_saves_answer_before_labels(tmp_path, monkeypatch):
    from app import prefs
    from app.web import tasks

    settings = SimpleNamespace(app_state_path=tmp_path / "app.sqlite", store_path=tmp_path / "knowledge.sqlite")
    conn = state.connect(settings.app_state_path)
    thread = state.create_chat_thread(conn)
    message = state.add_chat_message(conn, thread["thread_id"], role="reader", text="Hello")
    state.title_chat_thread(conn, thread["thread_id"], "Hello")
    prefs.write(conn, {prefs.LOCAL_OUTPUT_LANGUAGE: "tr", prefs.MARKET_REGION: "TR"})
    conn.close()
    prompts = []

    def complete(prompt):
        prompts.append(prompt)
        if "conversation metadata only" in prompt:
            # A completed answer is already durable while optional labels run.
            saved = state.connect(settings.app_state_path)
            try:
                assert state.chat_messages(saved, thread["thread_id"])[-1]["text"] == "Merhaba."
            finally:
                saved.close()
            return '{"title":"Kısa selamlaşma","followups":["Hangi ürünleri araştırabilirsin?"]}'
        return "Merhaba."

    monkeypatch.setattr(tasks, "_use_local_ask", lambda *_: True)
    monkeypatch.setattr(tasks, "_local_structured_completer", lambda *_: complete)
    monkeypatch.setattr(tasks, "_chat_web_accessors", lambda *_: (None, None))
    progress = SimpleNamespace(job_id="job-1", check=lambda: None, set=lambda *_: None,
                               log=lambda *_: None, partial=lambda *_: None)
    result = tasks.chat_ask(settings, {"thread_id": thread["thread_id"], "message_id": message["message_id"], "text": "Hello"}, progress)
    assert result["followups"] == ["Hangi ürünleri araştırabilirsin?"]
    assert "selected language: tr" in prompts[0] and "(TR)" in prompts[0]
    conn = state.connect(settings.app_state_path)
    try:
        assert state.get_chat_thread(conn, thread["thread_id"])["title"] == "Kısa selamlaşma"
        assert state.chat_messages(conn, thread["thread_id"])[-1]["followups"] == result["followups"]
    finally:
        conn.close()
