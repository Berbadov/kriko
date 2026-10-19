"""Labels cannot overwrite names; completing a batch cannot delete queued work."""


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

