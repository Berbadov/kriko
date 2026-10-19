"""The local API answers on this machine only, and says so rather than drifting.

`--host` was accepted with no guard while the module's own docstring says
binding anything else "is not a preference". A native client sends no `Origin`,
so the origin middleware would not have objected either: the only thing between
a reader's whole network and an unauthenticated API that can install packs and
open a terminal was nobody passing the flag.
"""

import pytest

from app.web import app as web_app


@pytest.fixture
def quiet_start(monkeypatch, tmp_path):
    """Stop at the point of serving: the spawn of CLIs is not this test's subject.

    The settings are isolated too — `main()` builds them from the environment,
    which points at the reader's own `~/.kriko`, and a test must never write
    there (`app/web/app.py` says so when it cannot open the file).
    """
    started = {}

    def fake_run(app, host="", port=0, **_kwargs):
        started["host"] = host
        started["port"] = port

    def fake_settings(**_overrides):
        from app.web.settings import Settings

        return Settings(store_path=tmp_path / "k.sqlite",
                        app_state_path=tmp_path / "app.sqlite")

    monkeypatch.setattr("uvicorn.run", fake_run)
    monkeypatch.setattr("app.providers.harness.warm_models", lambda: None)
    monkeypatch.setattr("app.modeldiscovery.cached", lambda: None)
    monkeypatch.setattr(web_app.Settings, "from_env", staticmethod(fake_settings))
    monkeypatch.delenv("KRIKO_ALLOW_LAN", raising=False)
    return started


def test_loopback_is_the_default(quiet_start):
    assert web_app.main([]) == 0
    assert quiet_start["host"] == "127.0.0.1"


def test_publishing_the_api_needs_a_deliberate_opt_in(quiet_start, capsys):
    with pytest.raises(SystemExit) as ended:
        web_app.main(["--host", "0.0.0.0"])
    assert ended.value.code == 2
    assert "no authentication" in capsys.readouterr().err
    assert quiet_start == {}, "nothing may be served after a refusal"


def test_the_opt_in_still_warns(monkeypatch, quiet_start, capsys):
    monkeypatch.setenv("KRIKO_ALLOW_LAN", "1")
    assert web_app.main(["--host", "0.0.0.0"]) == 0
    assert quiet_start["host"] == "0.0.0.0"
    assert "unauthenticated" in capsys.readouterr().err
