"""settings-10: `KRIKO_EXTENSION_BOUND` must reflect the port this process
actually asked for, not be left unset by the one entrypoint that never set it.

Before this fix, only `app.sidecar` (the desktop build) set the flag that
`/api/health`'s `extension_port_bound` reports. A plain `python -m app.web` —
the command the README itself gives, and the one a reader debugging the
extension on their own machine would run — left it unset, which
`Settings.from_env` (settings.py:150) reads as `False` regardless of what port
it is actually serving: About and Extension would assert "something else on
this machine took it" about a port nothing had probed.
"""

import os

import pytest
import uvicorn

from app.web import app as web_app
from app.web.settings import EXTENSION_PORT


@pytest.fixture(autouse=True)
def _no_real_server(monkeypatch):
    # main() ends in a blocking uvicorn.run(). The entrypoint must also stay
    # lazy: opening the app must not spawn catalog or CLI-help probes.
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: None)
    monkeypatch.setattr(web_app, "create_app", lambda settings: object())
    monkeypatch.setattr(
        "app.providers.harness.warm_models",
        lambda: pytest.fail("the app entrypoint started CLI probes"),
    )
    monkeypatch.setattr(
        "app.modeldiscovery.cached",
        lambda: pytest.fail("the app entrypoint started provider discovery"),
    )
    yield
    os.environ.pop("KRIKO_EXTENSION_BOUND", None)


def test_serving_the_extension_port_marks_it_bound():
    web_app.main(["--port", str(EXTENSION_PORT)])
    assert os.environ["KRIKO_EXTENSION_BOUND"] == "1"


def test_serving_any_other_port_marks_it_not_bound():
    web_app.main(["--port", str(EXTENSION_PORT + 100)])
    assert os.environ["KRIKO_EXTENSION_BOUND"] == "0"
