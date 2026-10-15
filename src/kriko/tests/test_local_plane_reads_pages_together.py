"""Pages that a query's hits name are downloaded together, in hit order.

Reading them one after another made a research run wait for the sum of its
downloads (measured: 70 s of reads that overlap to 18 s). The documents it
keeps, and their order, are exactly what one at a time kept.
"""

import threading
import time

from kriko.research.base import Fetched, ResearchTask
from kriko.research.local import LocalPlane


def task(**over):
    base = dict(
        subject_id="s1", subject_label="Widget MK2", subject_kind="widget",
        pack_id="p1", queries=["{label} common problems"],
        search_names=("Widget MK2",),
    )
    base.update(over)
    return ResearchTask(**base)


def hits(count):
    return [{"url": f"https://h{i}.test/p", "title": f"t{i}", "site": f"h{i}"}
            for i in range(count)]


def test_slow_pages_overlap_and_keep_their_order():
    def search(query, limit):
        return hits(4)

    def fetch(url):
        # The first page is the slowest: the order is the hits', not the finish's.
        time.sleep(0.4 if "h0" in url else 0.2)
        return Fetched(text=f"body of {url}", published_at="")

    plane = LocalPlane(search=search, fetch=fetch, complete=lambda prompt: "[]")
    started = time.monotonic()
    documents = plane.gather(task(max_documents=4))
    elapsed = time.monotonic() - started
    assert [d.url for d in documents] == [h["url"] for h in hits(4)]
    assert elapsed < 0.9, f"reads ran one after another ({elapsed:.2f}s)"


def test_it_never_fetches_more_than_the_run_wants_in_one_window():
    started = []
    lock = threading.Lock()

    def search(query, limit):
        return hits(8)

    def fetch(url):
        with lock:
            started.append(url)
        return "readable body"

    plane = LocalPlane(search=search, fetch=fetch, complete=lambda prompt: "[]")
    documents = plane.gather(task(max_documents=2))
    assert len(documents) == 2
    assert len(started) == 2, "a window larger than what is wanted over-fetches"


def test_an_unreadable_page_is_replaced_by_the_next_hit():
    def search(query, limit):
        return hits(3)

    def fetch(url):
        if "h0" in url:
            raise OSError("reset")
        return "readable body"

    plane = LocalPlane(search=search, fetch=fetch, complete=lambda prompt: "[]")
    documents = plane.gather(task(max_documents=2))
    assert [d.url for d in documents] == ["https://h1.test/p", "https://h2.test/p"]
