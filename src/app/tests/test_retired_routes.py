"""HTTP verbs this engine retired must stay retired.

Deleting a handler is a small edit and re-adding one is smaller still, often as
a side effect of restoring something next to it. The engine's answer is the
only durable assertion: a path listed here answers 404, so bringing it back is
a deliberate change with a test to update rather than a silent return.

Each case is a route the engine once served and no client calls any more. The
test is about the path, not about a response shape, because the shape is what
was retired.
"""

import pytest
from fastapi.testclient import TestClient

from app.web.app import create_app
from app.web.settings import Settings


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(Settings(
        store_path=tmp_path / "knowledge.sqlite",
        app_state_path=tmp_path / "app.sqlite",
        analysis_log_path=tmp_path / "analyses.jsonl",
    )))


@pytest.mark.parametrize(("method", "path", "body"), [
    # The freehand comparison board: the window saves the draft itself now,
    # and the word board means the slot rail (`docs/DESIGN.md`).
    ("GET", "/api/compare-drafts/a-draft/board", None),
    ("PUT", "/api/compare-drafts/a-draft/board", {"strokes": [], "notes": []}),
    # The legacy header counts: `/api/health` and `/api/usage/meters` are the
    # two surfaces the window reads now.
    ("GET", "/api/status", None),
    # The one-page price lookup; `POST /api/buyer/page` is the page read the
    # window and extension use.
    ("GET", "/api/prices/page", None),
    # The one-click browser launch; setup stages the extension (`/stage`) and
    # opens its folder (`/reveal`) instead.
    ("POST", "/api/extension/launch", None),
    # The quick-look follow-up pair; `/api/jobs/{id}/say` and the job thread
    # carry the conversation now.
    ("POST", "/api/extension/quick-look/a-job/ask", {"q": "Is it quiet?"}),
    ("GET", "/api/extension/quick-look/a-job/asks", None),
    # The SSE duplicate of the operations feed; `/api/operations` polls.
    ("GET", "/api/operations/stream", None),
], ids=["compare-board-read", "compare-board-write", "status",
        "prices-page", "extension-launch", "quick-look-ask",
        "quick-look-asks", "operations-stream"])
def test_a_retired_route_answers_404(client, method, path, body):
    answer = client.request(method, path, json=body)
    assert answer.status_code == 404, (
        f"{method} {path} answered {answer.status_code}; this route was retired"
    )
