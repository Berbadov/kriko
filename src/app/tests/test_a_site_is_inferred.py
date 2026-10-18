"""Working out how to read a page with a model, from what the browser saw.

The reader's ask: *"Site recognition needs an AI to figure out the reading
structure via web extension's data."* Until `app/siteinfer.py` existed, a page
was readable if a pack's URL glob matched it or if its schema.org data happened
to fit a pack's any-site adapter — and otherwise the reader pressed a button
that spends a coding-agent run.

Every claim below is about one half of that: what an inference produces and how
it is checked, what it costs when it is asked again, what the reader is given
to see and undo, and — the property that matters most — that an installation
with no model ready answers exactly as it did before any of this existed.
"""

import json
import textwrap

import pytest
from fastapi.testclient import TestClient

from app import siteinfer, sites
from app.web import state
from app.web.app import create_app
from app.web.settings import Settings
from kriko.pack import build
from kriko.store import packstore
from kriko.store.db import connect

TOML = """
    [pack]
    id = "machines"
    name = "Machines"
    version = "0.1.0"
    license = "CC0-1.0"
    [identity]
    product = ["brand", "model"]
"""

TERMS = """
    - {term_id: product, role: subject_kind}
    - {term_id: brand, role: attribute, datatype: text, match: {required: true}}
    - {term_id: model, role: attribute, datatype: text, match: {required: true}}
    - {term_id: fuel, role: attribute, datatype: text}
    - {term_id: usage_km, role: context_key, datatype: number, unit: km}
    - {term_id: mech, role: domain}
"""

SUBJECTS = """
    - kind: product
      label: Acme Roadster
      identity: {brand: acme, model: roadster}
      aliases: ["Acme Roadster"]
"""

CLAIMS = """
    - subject: {kind: product, identity: {brand: acme, model: roadster}}
      kind: known_issue
      domain: mech
      severity: high
      text: {en: {title: Timing chain stretches early, body: b, advice: a}}
      evidence:
        - {url: "https://e.invalid/x", quote: Chains go at 80k.}
"""

#: The site the reader is standing on. Invented, like every host in this suite:
#: nothing here may pass because of which packs happen to be in the tree.
SITE = "shop.invalid"
PAGE_URL = f"https://{SITE}/p/roadster-1"

#: What the extension sends: the page's own labels, in its own words, and no
#: interpretation of any of them.
PAGE = {"Marka": "Acme", "Model": "Roadster", "Yıl": "2014"}


def _adapter(labels, *, site=SITE, match=None, extra=None) -> str:
    """A model's reply: one JSON object in a fence, as the brief asks for."""
    spec = {
        "id": f"local.{SITE}",
        "site": site,
        "match": match if match is not None else [f"*://*.{SITE}/*"],
        "identity": {key: {"labels": [label]} for key, label in labels.items()},
    }
    spec.update(extra or {})
    return "```json\n" + json.dumps(spec) + "\n```"


#: What a working model answers for `PAGE`: two identity keys the pack already
#: declares, read off the labels the page prints.
READS_THE_PAGE = _adapter({"brand": "Marka", "model": "Model"})


class _Model:
    """A stand-in for the reader's local model: one reply, and a call count."""

    def __init__(self, *replies, error=None, delay=0.0):
        self.replies = list(replies)
        self.error = error
        self.delay = delay
        self.calls = 0
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        if self.delay:
            import time

            time.sleep(self.delay)
        if self.error is not None:
            raise self.error
        if not self.replies:
            return ""
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


def _ready(monkeypatch, model: _Model, *, model_name: str = "test-model") -> _Model:
    """Let inference find a model server: the one seam that is not under test here.

    Everything after this — the prompt, the parse, the two gates, the cache,
    the storage — is the real code path.
    """
    def plane(app_state_path, *, timeout=siteinfer.CALL_TIMEOUT):
        return {"ready": True, "complete": model, "model": model_name, "reason": ""}

    monkeypatch.setattr(siteinfer, "plane", plane)
    return model


@pytest.fixture
def installed(tmp_path) -> Settings:
    root = tmp_path / "p"
    for sub in ("vocabulary", "data", "research", "adapters"):
        (root / sub).mkdir(parents=True)
    (root / "pack.toml").write_text(textwrap.dedent(TOML), encoding="utf-8")
    (root / "vocabulary" / "terms.yaml").write_text(textwrap.dedent(TERMS), encoding="utf-8")
    (root / "data" / "subjects.yaml").write_text(textwrap.dedent(SUBJECTS), encoding="utf-8")
    (root / "data" / "claims.yaml").write_text(textwrap.dedent(CLAIMS), encoding="utf-8")
    (root / "research" / "principle.md").write_text("Only the expensive.", encoding="utf-8")
    (root / "research" / "templates.yaml").write_text('- "{alias} faults"\n', encoding="utf-8")
    store_path = tmp_path / "store.sqlite"
    conn = connect(store_path)
    packstore.install(conn, build.build(root, tmp_path / "p.kpack"))
    conn.close()
    return Settings(
        store_path=store_path,
        analysis_log_path=tmp_path / "analyses.jsonl",
        app_state_path=tmp_path / "app.sqlite",
    )


@pytest.fixture
def client(installed) -> TestClient:
    return TestClient(create_app(installed))


def _analyze(client, **body):
    body.setdefault("url", PAGE_URL)
    body.setdefault("origin", "extension")
    body.setdefault("fields", PAGE)
    response = client.post("/api/analyze", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _conn(settings):
    return state.connect(settings.app_state_path)


# ── a page nothing installed reads, read by this machine's model ─────────────


def test_a_page_nothing_installed_reads_is_read_by_this_machines_model(
    client, installed, monkeypatch
):
    """The whole feature, end to end: labels in, an adapter out, claims back."""
    model = _ready(monkeypatch, _Model(READS_THE_PAGE))

    body = _analyze(client)

    assert body.get("readable") is not False
    assert body["read_by"] == "inferred"
    assert [claim["title"] for claim in body["claims"]] == [
        "Timing chain stretches early"]
    assert model.calls == 1
    # The page's own words reach the model, and the identity keys it may map
    # into are the installed packs' — both are the brief's job, and both are
    # visible in what was actually sent.
    assert "Marka: Acme" in model.prompts[0]
    assert "`brand`" in model.prompts[0] and "`model`" in model.prompts[0]


def test_the_adapter_is_stored_as_an_inference_and_named_as_one(
    client, installed, monkeypatch
):
    """The third value of `local_adapters.source`, and every reader of it."""
    _ready(monkeypatch, _Model(READS_THE_PAGE))
    _analyze(client)

    conn = _conn(installed)
    (row,) = state.local_adapters(conn)
    assert row["source"] == "inference"
    assert row["host"] == SITE

    # The extension's own list: a site it must inject on, and how it was learned.
    listed = [one for one in client.get("/api/adapters").json()
              if one["site"] == SITE]
    assert listed and listed[0]["learned_by"] == "inference"

    # The Sites screen's list: the same fact, where the reader can see it.
    registered = [one for one in client.get("/api/sites").json()["registered"]
                  if one["site"] == SITE]
    assert registered[0]["learned_by"] == "inference"
    assert registered[0]["enabled"] is True


def test_an_adapter_that_reads_nothing_is_refused_and_never_stored(
    client, installed, monkeypatch
):
    """The gate a hand-written adapter passes, applied to a model's guess."""
    model = _ready(monkeypatch, _Model(_adapter({"brand": "Baska Etiket"})))

    body = _analyze(client)

    assert body["readable"] is False
    assert body["reason"] == "no_adapter"
    assert state.local_adapters(_conn(installed)) == []
    assert model.calls == 1
    # And the refusal is remembered: a shop whose every listing carries the
    # same labels does not pay for the same failed call per page.
    _analyze(client, url=f"https://{SITE}/p/other")
    assert model.calls == 1


def test_an_inferred_adapter_may_not_claim_another_site(client, installed, monkeypatch):
    """`site` becomes a host permission, and it is not the model's to choose."""
    _ready(monkeypatch, _Model(_adapter(
        {"brand": "Marka"},
        site="evil.test", match=["*://*.evil.test/*"])))

    body = _analyze(client)

    assert body["reason"] == "no_adapter"
    assert state.local_adapters(_conn(installed)) == []


def test_a_key_the_engine_never_reads_cannot_be_stored_as_though_it_could(
    client, installed, monkeypatch
):
    """`selector` is not in the vocabulary: an adapter is data, never markup."""
    _ready(monkeypatch, _Model(_adapter({"brand": "Marka"}, extra={
        "identity": {"brand": {"labels": ["Marka"], "selector": ".product-brand"}},
    })))

    assert _analyze(client)["read_by"] == "inferred"

    conn = _conn(installed)
    (row,) = state.local_adapters(conn)
    assert row["spec"]["identity"]["brand"] == {"labels": ["Marka"]}


def test_an_identity_key_no_pack_declares_is_refused(client, installed, monkeypatch):
    """A key nobody knows resolves every page to nothing, so nothing is stored."""
    _ready(monkeypatch, _Model(_adapter({"marka": "Marka"})))

    assert _analyze(client)["reason"] == "no_adapter"
    assert state.local_adapters(_conn(installed)) == []


def test_a_partial_inference_cannot_hide_a_broken_mapping_in_the_title(installed, monkeypatch):
    _ready(monkeypatch, _Model(_adapter({}, extra={"identity": {
        "brand": {"labels": ["Marka"]},
        "model": {"labels": ["Invented"], "from": "title", "vocabulary": "model"},
    }})))
    with connect(installed.store_path) as store, state.connect(installed.app_state_path) as conn:
        assert siteinfer.infer(store, conn, app_state_path=installed.app_state_path,
                               url=PAGE_URL, fields=PAGE, title="Acme Roadster") is None
        assert state.local_adapters(conn) == []
        assert "absent" in state.site_inferences(conn)[0]["detail"]


def test_known_sites_keep_new_browser_facts_for_the_next_learning_run(client, installed, monkeypatch):
    _ready(monkeypatch, _Model(READS_THE_PAGE))
    _analyze(client)
    _analyze(client, fields={**PAGE, "New specification": "R2"})
    with state.connect(installed.app_state_path) as conn:
        assert state.site_sample(conn, SITE)["facts"]["New specification"] == "R2"


def test_an_agent_corrects_its_mapping_from_the_sample_failure(installed, monkeypatch):
    from types import SimpleNamespace
    from app.providers import harness
    from app.web import tasks

    model = _Model(_adapter({"brand": "Invented"}), READS_THE_PAGE)
    agent = SimpleNamespace(ask=model)
    monkeypatch.setattr(harness, "available", lambda: [object()])
    monkeypatch.setattr("app.providers.harness_researcher", lambda **kw: agent)
    with state.connect(installed.app_state_path) as conn:
        state.record_site_request(conn, host=SITE, url=PAGE_URL,
                                  sample=sites.sample(url=PAGE_URL, fields=PAGE))
    progress = SimpleNamespace(set=lambda *a: None, log=lambda *a: None,
                               check=lambda: None, replies=lambda: [])
    result = tasks.site_register(installed, {"host": SITE}, progress)
    assert model.calls == 2
    assert "absent from the browser snapshot" in model.prompts[1]
    assert result["reading"]["identity"] == {"brand": "Acme", "model": "Roadster"}


def test_a_page_with_nothing_labelled_on_it_costs_no_model_call(
    client, installed, monkeypatch
):
    """A call with nothing to read is a call per page for no answer at all."""
    model = _ready(monkeypatch, _Model(READS_THE_PAGE))

    assert _analyze(client, fields={})["reason"] == "no_adapter"
    assert model.calls == 0


# ── what the model is asked for ─────────────────────────────────────────────


def test_the_prompt_demands_the_vocabulary_the_engine_reads():
    """Item for item, the keys `kriko/adapters.py` interprets and no others."""
    text = siteinfer.prompt_for(
        SITE, PAGE_URL, "* `machines` / `product`: `brand`, `model`",
        sites.sample(url=PAGE_URL, title="Acme", fields=PAGE))

    assert '"identity"' in text
    # Named only to forbid it — the old brief asked for it as a field.
    assert '"title_patterns"' not in text
    assert "no `title_patterns`" in text
    for key in sites.RULE_KEYS:
        assert f"`{key}`" in text, key
    # A single turn with no tools: the agent brief's "read one more listing"
    # is not something a completion can do, so it is said outright.
    assert "You cannot fetch anything" in text


def test_the_page_shape_is_its_labels_and_never_their_values():
    """The cache key, or a site would re-infer on every price it lists."""
    assert siteinfer.shape_of({"Marka": "Acme"}) == siteinfer.shape_of({"marka": "Other"})
    assert siteinfer.shape_of({"Marka": "a", "Model": "b"}) == \
        siteinfer.shape_of({"Model": "b", "Marka": "a"})
    # The structured-data type is the second half of "what kind of page is
    # this": a shop's Product and a vehicle site's Car read differently even
    # when their label sets look alike.
    assert siteinfer.shape_of({"Marka": "a", "ld:@type": "product"}) != \
        siteinfer.shape_of({"Marka": "a", "ld:@type": "car"})
    assert siteinfer.shape_of({"Marka": "a"}) != siteinfer.shape_of({"Satıcı": "a"})


# ── when the model changes, or the site does ────────────────────────────────


def test_a_redesigned_site_is_inferred_again(client, installed, monkeypatch):
    """A stored guess stops reading, and the new shape is the evidence."""
    model = _ready(monkeypatch, _Model(
        READS_THE_PAGE,
        _adapter({"brand": "Satici", "model": "Seri"}),
    ))
    assert _analyze(client)["read_by"] == "inferred"

    # The site's markup changed: none of the stored adapter's labels are on
    # the page any more, so it resolves an empty identity.
    body = _analyze(client, url=f"https://{SITE}/p/2",
                    fields={"Satici": "Acme", "Seri": "Roadster"})

    assert model.calls == 2
    assert body["read_by"] == "inferred"
    assert [claim["title"] for claim in body["claims"]] == [
        "Timing chain stretches early"]
    (row,) = state.local_adapters(_conn(installed))
    assert row["spec"]["identity"]["brand"]["labels"] == ["Satici"]


def test_a_failed_inference_is_a_brake_that_expires(client, installed, monkeypatch):
    """A model that was loading is not a model that cannot read the site.

    The brake is what stops a reader browsing one shop paying twelve seconds a
    page; the expiry is what stops one unlucky first page leaving that shop
    uninferable for good with nothing on any screen to say so.
    """
    from datetime import UTC, datetime, timedelta

    model = _ready(monkeypatch, _Model(error=RuntimeError("model is still loading")))

    assert _analyze(client)["reason"] == "no_adapter"
    assert model.calls == 1
    (row,) = state.site_inferences(_conn(installed))
    assert row["state"] == "failed"

    # Still a brake, right now: the second page of the same shape is free.
    _analyze(client, url=f"https://{SITE}/p/2")
    assert model.calls == 1

    # And not a scar: once the record is older than the window, the shape is
    # the model's to answer again.
    conn = _conn(installed)
    conn.execute("UPDATE site_inference SET at = ?", (
        (datetime.now(UTC) - timedelta(seconds=siteinfer.FAILED_BRAKE_SECONDS + 60)
         ).isoformat(timespec="seconds"),))
    conn.commit()
    _analyze(client, url=f"https://{SITE}/p/3")
    assert model.calls == 2


def test_a_refusal_never_expires(client, installed, monkeypatch):
    """The model answered. That is a fact about the page, not about the clock."""
    from datetime import UTC, datetime, timedelta

    model = _ready(monkeypatch, _Model(_adapter({"brand": "Baska Etiket"})))
    assert _analyze(client)["reason"] == "no_adapter"
    assert model.calls == 1

    conn = _conn(installed)
    conn.execute("UPDATE site_inference SET at = ?", (
        (datetime.now(UTC) - timedelta(days=30)).isoformat(timespec="seconds"),))
    conn.commit()

    _analyze(client, url=f"https://{SITE}/p/2")
    assert model.calls == 1


# ── failing open, in every direction ────────────────────────────────────────


def test_a_model_that_errors_leaves_the_answer_the_reader_always_got(
    client, installed, monkeypatch
):
    """An inference failure is never an error the reader sees as a crash."""
    _ready(monkeypatch, _Model(error=RuntimeError("no runner for this model")))

    body = _analyze(client)

    assert body["readable"] is False
    assert body["reason"] == "no_adapter"
    assert state.local_adapters(_conn(installed)) == []
    # And the reader's press still does what it always did: it becomes an ask.
    seen = client.post("/api/sites/seen", json={"url": PAGE_URL, "fields": PAGE})
    assert seen.status_code == 200
    assert seen.json()["readable"] is False
    assert seen.json()["request"]["host"] == SITE


def test_a_model_that_does_not_answer_in_time_is_abandoned():
    """The request's own clock, not the socket's: the permit queue is unbounded.

    `app/providers/network.py` waits for a host permit with no timeout, so a
    local model busy with the reader's research run would hold a page's request
    open until the extension gave up on Kriko entirely. The bound lives here.
    """
    import time

    started = time.monotonic()
    reply, why = siteinfer._bounded(lambda prompt: time.sleep(0.6) or "late", "p", 0.05)

    assert reply == ""
    assert "did not answer" in why
    assert time.monotonic() - started < 0.5, "the wait outlived its own budget"


def test_nothing_is_inferred_when_no_model_plane_is_ready(client, installed):
    """**The property that matters most.**

    No model server answers (the suite stubs discovery off), no coding agent is
    picked, and a key in the environment is not a reason to start one. The
    installation answers exactly as it did before any of this existed — and
    says so in a shape the panel already understands.
    """
    from app.providers import completer_for

    def _never(*args, **kwargs):
        raise AssertionError("the paid plane was started for an inference")

    import app.providers as providers

    real = providers.completer_for
    providers.completer_for = _never
    try:
        body = _analyze(client)
    finally:
        providers.completer_for = real
    assert body["readable"] is False
    assert body["reason"] == "no_adapter"
    assert body["readable_sites"] == []
    assert state.local_adapters(_conn(installed)) == []
    # Nothing recorded either: the reader starting their model later must have
    # their pages inferred, not be told these shapes were already tried.
    assert state.site_inferences(_conn(installed)) == []
    assert completer_for is providers.completer_for


def test_the_plane_is_this_machines_model_or_nothing(tmp_path, monkeypatch):
    """A key that happened to be saved is not a plane anyone chose."""
    import app.providers as providers

    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-a-reason")

    def _never(*args, **kwargs):
        raise AssertionError("an inference reached the paid plane")

    monkeypatch.setattr(providers, "completer_for", _never)

    found = siteinfer.plane(tmp_path / "app.sqlite")

    assert found["ready"] is False
    assert found["complete"] is None
    assert "local model" in found["reason"].lower()


def test_the_reader_is_never_the_one_who_waits_for_a_failure(client, installed, monkeypatch):
    """A refused adapter is a log line, not a 500 or a red panel."""
    _ready(monkeypatch, _Model("I could not work out this page."))

    body = _analyze(client)

    assert body["reason"] == "no_adapter"
    rows = state.site_inferences(_conn(installed))
    assert rows and rows[0]["state"] == "refused"


# ── seeing it, and turning it off ───────────────────────────────────────────


def test_the_reader_can_see_that_a_site_was_inferred_and_turn_it_off(
    client, installed, monkeypatch
):
    """The one piece of site knowledge nobody wrote, with a switch."""
    _ready(monkeypatch, _Model(READS_THE_PAGE))
    assert _analyze(client)["read_by"] == "inferred"

    def listed():
        return [one["site"] for one in client.get("/api/adapters").json()]

    def screen():
        return [one for one in client.get("/api/sites").json()["registered"]
                if one["site"] == SITE][0]

    assert SITE in listed()          # the extension injects there
    assert screen()["enabled"] is True

    off = client.post(f"/api/sites/{SITE}/inferred", json={"enabled": False}).json()
    assert off == {"host": SITE, "enabled": False, "changed": True}

    # Off means off: no injection target, no reading, and the ask comes back —
    # while the row stays on the screen with the switch that undoes it.
    assert SITE not in listed()
    assert screen()["enabled"] is False
    assert screen()["learned_by"] == "inference"
    assert client.post("/api/sites/seen", json={"url": PAGE_URL}).json()["readable"] is False
    assert [row["host"] for row in client.get("/api/sites").json()["requested"]] == [SITE]

    on = client.post(f"/api/sites/{SITE}/inferred", json={"enabled": True}).json()
    assert on["changed"] is True
    assert SITE in listed()
    assert client.post("/api/sites/seen", json={"url": PAGE_URL}).json()["readable"] is True


def test_a_site_the_reader_turned_off_is_not_inferred_again(
    client, installed, monkeypatch
):
    """Off is per site, not per page shape: a switch a later page flips back
    by inferring a second adapter is not a switch."""
    model = _ready(monkeypatch, _Model(READS_THE_PAGE))
    _analyze(client)
    assert model.calls == 1
    conn = _conn(installed)
    state.set_local_adapter_enabled(conn, SITE, False)

    body = _analyze(client, url=f"https://{SITE}/p/2",
                    fields={"Satici": "Acme", "Seri": "Roadster"})

    assert model.calls == 1
    assert body["reason"] == "no_adapter"
    (row,) = state.local_adapters(conn, enabled_only=False)
    assert row["enabled"] == 0


def test_an_adapter_somebody_wrote_is_not_this_doors_to_close(client, installed):
    """An agent's or a reader's own is theirs; only a guess is turn-off-able."""
    conn = _conn(installed)
    state.save_local_adapter(
        conn, host=SITE,
        spec=sites.check({"site": SITE, "identity": {"brand": {"labels": ["Marka"]}}}))

    answer = client.post(f"/api/sites/{SITE}/inferred", json={"enabled": False})
    assert answer.status_code == 404
    assert "inferred" in answer.json()["detail"]
    assert state.local_adapters(conn)[0]["enabled"] == 1


def test_forgetting_an_inferred_site_lets_it_be_learned_again(
    client, installed, monkeypatch
):
    """Forget is forget: the brake goes with the adapter it was holding back."""
    model = _ready(monkeypatch, _Model(READS_THE_PAGE, READS_THE_PAGE))
    _analyze(client)
    assert model.calls == 1

    assert client.delete(f"/api/sites/{SITE}").json()["forgotten"] is True
    conn = _conn(installed)
    assert state.local_adapters(conn) == []
    assert state.site_inferences(conn) == []

    assert _analyze(client)["read_by"] == "inferred"
    assert model.calls == 2


def test_the_press_is_where_the_browsers_own_labels_are_inferred(
    client, installed, monkeypatch
):
    """`/api/sites/seen` carries the explore scrape, so it is used there too."""
    _ready(monkeypatch, _Model(READS_THE_PAGE))

    answer = client.post("/api/sites/seen", json={
        "url": PAGE_URL, "fields": PAGE, "page_title": "Acme Roadster",
        "product": {"name": "Acme Roadster"},
    }).json()

    assert answer["readable"] is True
    assert answer["inferred"] is True
    assert state.local_adapters(_conn(installed))[0]["source"] == "inference"
    # No ask is left behind for a site that is now readable.
    assert client.get("/api/sites").json()["requested"] == []
