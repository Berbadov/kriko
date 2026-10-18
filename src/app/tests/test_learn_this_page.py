"""Learn this page: the reader presses it, and an agent goes through the page.

The reader's report, after trying a quick look from the panel on a price-
comparison listing: the searches were the page's whole `<title>`, shop name and
ranking words included, and they came back with chemistry lessons. Two things
were wrong and each has its own half below: the name taken from a page, and the
missing way to tell Kriko "study this page and learn what to take from it".

Every host in this suite is invented, like the rest of the suite's.
"""

# The fixtures are the inference suite's own: the same packs, the same fake
# model seam, so nothing here can pass because of which packs are in the tree.
# They are imported for pytest to find, and a test that takes one as an argument
# redefines the import on purpose.
# ruff: noqa: F811
from app import pagetitle, siteinfer
from app.tests.test_a_site_is_inferred import (  # noqa: F401
    PAGE,
    PAGE_URL,
    READS_THE_PAGE,
    SITE,
    _adapter,
    _conn,
    _Model,
    _ready,
    client,
    installed,
)
from app.web import state

# ── the name a page gives its product ────────────────────────────────────────


def test_a_comparison_sites_title_is_cut_back_to_the_product():
    title = ("Samsung Galaxy A54 256 GB Beyaz Fiyatları, Özellikleri ve Yorumları"
             " | En Ucuzu Akakçe")
    assert pagetitle.product_name(title, "https://www.akakce.com/x.html") == (
        "Samsung Galaxy A54 256 GB Beyaz")


def test_the_shop_is_dropped_wherever_the_title_puts_it():
    assert pagetitle.product_name(
        "Shop.invalid : Acme Roadster 2 Wireless", "https://www.shop.invalid/p/1"
    ) == "Acme Roadster 2 Wireless"
    assert pagetitle.product_name(
        "Acme Roadster - Preise, Test und Bewertungen | Shop", "https://shop.invalid/p/1"
    ) == "Acme Roadster"


def test_a_name_that_is_all_page_words_or_has_nothing_to_cut_is_kept():
    assert pagetitle.product_name("Kingston A400 SSD 480GB") == "Kingston A400 SSD 480GB"
    assert pagetitle.product_name("Wi-Fi 6 Router") == "Wi-Fi 6 Router"
    assert pagetitle.product_name("Test") == "Test"
    assert pagetitle.product_name("") == ""


def test_the_name_the_panel_sends_is_cleaned_but_the_readers_context_is_kept(
    client, monkeypatch
):
    seen = {}

    def resolve(store, *, q, subject_id):
        seen["q"] = q
        raise AssertionError("stop here: the name is all this test reads")

    from app.web.routers import extension

    monkeypatch.setattr(extension, "resolve_research_subject", resolve)
    try:
        client.post("/api/extension/research-plane", json={
            "q": "Acme Roadster Fiyatları, Özellikleri ve Yorumları | En Ucuzu Shop"
                 " · the red one",
            "url": "https://www.shop.invalid/p/1",
        })
    except AssertionError:
        pass
    assert seen["q"] == "Acme Roadster · the red one"


# ── pressing the button ──────────────────────────────────────────────────────


def _press(client, **body):
    body.setdefault("url", PAGE_URL)
    body.setdefault("fields", PAGE)
    body.setdefault("page_title", "Acme Roadster | Shop")
    body.setdefault("product", {"name": "Acme Roadster"})
    response = client.post("/api/sites/learn", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_pressing_learn_shows_what_was_taken_from_the_page(client, installed, monkeypatch):
    _ready(monkeypatch, _Model(READS_THE_PAGE))

    lesson = _press(client)

    assert lesson["learned"] is True and lesson["mode"] == "local"
    assert lesson["name"] == "Acme Roadster"
    grabs = {one["as"]: one["value"] for one in lesson["grabs"]}
    assert grabs["brand"] == "Acme" and grabs["model"] == "Roadster"
    # And it is kept: the page is readable now, by something nobody wrote.
    assert state.local_adapters(_conn(installed))[0]["source"] == "inference"


def test_a_press_tries_again_where_a_page_load_would_not(client, installed, monkeypatch):
    """A refusal is a judgement about an answer, and the reader asked for another."""
    model = _ready(monkeypatch, _Model(_adapter({"brand": "Baska Etiket"}), READS_THE_PAGE))

    first = _press(client)
    assert first["learned"] is False and first["reason"]
    again = _press(client)

    assert again["learned"] is True
    assert model.calls == 2


def test_a_press_says_why_when_nothing_was_learned(client, installed, monkeypatch):
    _ready(monkeypatch, _Model(error=TimeoutError("slow")))
    lesson = _press(client)
    assert lesson["learned"] is False
    assert "did not" in lesson["reason"] or "could not" in lesson["reason"]

    empty = _press(client, fields={})
    assert empty["learned"] is False
    assert "no labelled facts" in empty["reason"]


def test_a_press_switches_a_site_the_reader_had_turned_off_back_on(
    client, installed, monkeypatch
):
    _ready(monkeypatch, _Model(READS_THE_PAGE))
    _press(client)
    client.post(f"/api/sites/{SITE}/inferred", json={"enabled": False})
    assert state.local_adapters(_conn(installed), enabled_only=True) == []

    _press(client)

    assert len(state.local_adapters(_conn(installed), enabled_only=True)) == 1


def test_a_press_uses_this_machines_model_even_when_another_agent_is_picked(
    installed, monkeypatch
):
    """The pick governs research runs. This is one free call the reader asked for."""
    from app import localplane

    monkeypatch.setattr(localplane, "reader_chose_an_agent", lambda path: True)
    monkeypatch.setattr(localplane, "resolve", lambda path, with_search=False: {
        "ready": False, "reason": "no server"})

    quiet = siteinfer.plane(installed.app_state_path)
    pressed = siteinfer.plane(installed.app_state_path, pressed=True)

    assert quiet["reason"].startswith("the reader picked another agent")
    # Past the pick, so the only thing left to say is the server's own reason.
    assert pressed["reason"] == "no server"


def test_another_agent_is_a_job_to_follow_and_never_a_blocking_call(
    client, installed, monkeypatch
):
    submitted = {}

    class Runner:
        def submit(self, kind, params, **_):
            submitted.update(kind=kind, params=params)
            return "job-1"

    client.app.state.jobs = Runner()
    model = _ready(monkeypatch, _Model(READS_THE_PAGE))

    lesson = _press(client, agent="claude")

    assert lesson["mode"] == "agent" and lesson["job_id"] == "job-1"
    assert submitted["kind"] == "site_register"
    assert submitted["params"]["harness"] == "claude"
    assert submitted["params"]["sample"]["facts"]["Marka"] == "Acme"
    assert model.calls == 0


def test_a_small_model_is_given_key_names_and_not_pack_names(installed):
    """It took the pack's id for a key and was refused for mapping into nothing.

    The agents read the grouped list well; the local model's single turn gets the
    keys alone, each once, said to be keys and not packs.
    """
    from app.web.tasks import identity_keys_text
    from kriko.store.db import connect

    conn = connect(installed.store_path)
    try:
        flat = identity_keys_text(conn, flat=True)
        grouped = identity_keys_text(conn)
    finally:
        conn.close()
    assert "`brand`" in flat and "`model`" in flat
    assert "machines" not in flat, "a pack's id is what the model mistook for a key"
    assert "machines" in grouped, "the agents' own list is unchanged"
