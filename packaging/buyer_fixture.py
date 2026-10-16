"""Serve isolated synthetic recent checks and comparison drafts for screenshots.

The caller supplies a scratch directory. The ready file names the URL only
after fixture data has been built; no real store, lifespan jobs, or agents run.
"""

from __future__ import annotations

import json
import ast
import os
import socket
import sys
import textwrap
from pathlib import Path

scratch = Path(sys.argv[1]).resolve()
data = scratch / "data"
data.mkdir(parents=True, exist_ok=True)
os.environ["KRIKO_LOG"] = str(data / "engine.log")

import uvicorn  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from app import chat  # noqa: E402
from app.web import state  # noqa: E402
from app.web.app import create_app  # noqa: E402
from app.web.routers.query import LookupRequest, answer  # noqa: E402
from app.web.settings import Settings  # noqa: E402
from kriko.pack import build  # noqa: E402
from kriko.store import packstore  # noqa: E402
from kriko.store.db import connect  # noqa: E402

# Read only the neutral fixture's literal data. Importing the test module
# would pull pytest into a packaging job that installs runtime dependencies.
fixture_source = Path(__file__).resolve().parents[1] / "src/app/tests/test_chat_sources.py"
fixture_values = {
    node.targets[0].id: ast.literal_eval(node.value)
    for node in ast.parse(fixture_source.read_text(encoding="utf-8")).body
    if isinstance(node, ast.Assign) and len(node.targets) == 1
    and isinstance(node.targets[0], ast.Name)
    and node.targets[0].id in {"CLAIMS", "SUBJECTS", "TERMS", "TOML"}
}
CLAIMS, SUBJECTS, TERMS, TOML = (fixture_values[key] for key in
                               ("CLAIMS", "SUBJECTS", "TERMS", "TOML"))


def main() -> None:
    pack = data / "pack"
    (pack / "vocabulary").mkdir(parents=True, exist_ok=True)
    (pack / "data").mkdir(exist_ok=True)
    for name, content in (
        ("pack.toml", TOML),
        ("vocabulary/terms.yaml", TERMS),
        ("data/subjects.yaml", SUBJECTS),
        ("data/claims.yaml", CLAIMS),
    ):
        (pack / name).write_text(textwrap.dedent(content), encoding="utf-8")

    store = connect(data / "knowledge.sqlite")
    packstore.install(store, build.build(pack, data / "gears.kpack"))
    app_db = state.connect(data / "app.sqlite")
    checks = []
    for model, label in (("alpha200", "Alpha Unit 200"), ("beta300", "Beta Unit 300")):
        request = LookupRequest(kind="product", identity={"brand": "acme", "model": model})
        response, _ = answer(store, request)
        checks.append(state.record_lookup(
            app_db, source="review", label=label,
            request=request.model_dump(), response=response,
        ))
    state.save_compare_draft(app_db, "Alpha first", checks)
    state.save_compare_draft(app_db, "Beta first", list(reversed(checks)))
    state.create_chat_thread(app_db, "Existing conversation")
    thread = state.create_chat_thread(app_db, "Compare the synthetic products")
    state.add_chat_message(app_db, thread["thread_id"], role="reader",
                           text="Help me choose between Alpha Unit 200 and Beta Unit 300.")
    state.add_chat_message(
        app_db, thread["thread_id"], role="agent",
        text=("**Synthetic review data**\n\n"
              "Alpha Unit 200 has a sourced report of overheating under long loads. "
              "Beta Unit 300 has a sourced report of a short cable. These records "
              "describe different problems; fewer recorded problems alone cannot "
              "establish that either product is safer.\n\n"
              "- Check the operating conditions against your intended use.\n"
              "- Confirm the cable length and power requirements before deciding.\n\n"
              "The catalog does not establish a current price or availability. "
              "What will you use it for, and what is your budget?"),
        steps=[{"id": "saved", "source": "saved_checks", "label": "Read 2 saved checks",
                "state": "done", "rows": 2, "ms": 40}],
        sources=["https://maker.example.test/alpha", "https://maker.example.test/beta"],
    )
    store.close()
    app_db.close()

    settings = Settings(
        store_path=data / "knowledge.sqlite",
        app_state_path=data / "app.sqlite",
        analysis_log_path=data / "analyses.jsonl",
        packs_dir=data / "packs",
        dist_dir=data / "dist",
        pack_index_url="http://127.0.0.1:1/no-index",
    )
    app = create_app(settings)

    @app.middleware("http")
    async def fixture_boundaries(request, call_next):
        path = request.url.path
        if "--desktop-review" in sys.argv:
            model_names = ["review-small:3b", "review-medium:8b", "review-large:14b"]
            if path == "/api/prefs":
                return JSONResponse({"harnesses": [
                    {"id": "local", "label": "Local model", "llm": model_names[0]},
                    {"id": "claude-code", "label": "Claude Code", "llm": "review-model",
                     "llm_selectable": True, "llms": ["review-model", "review-alternative"]}],
                    "missing": [{"id": "codex", "label": "Codex", "install_hint": "Synthetic review entry."}],
                    "chosen": {"preferred_harness": "local"}})
            if path == "/api/agent-targets":
                return JSONResponse({"targets": []})
            if path == "/api/local-plane":
                return JSONResponse({"ready": True, "model": model_names[0], "models": model_names,
                                     "name": "Ollama", "url": "http://127.0.0.1:11434",
                                     "line": "Synthetic desktop review data", "search_label": "Review fixture",
                                     "servers": [{"name": "Ollama", "url": "http://127.0.0.1:11434",
                                                  "up": True, "models": model_names}]})
            if path == "/api/local-models":
                return JSONResponse({"models": [{"name": name, "params": size, "quant": "Q4_K_M",
                                                 "size_bytes": (i + 1) * 2_000_000_000}
                                                for i, (name, size) in enumerate(zip(model_names, ["3B", "8B", "14B"]))],
                                     "library": [{"name": "review-small", "sizes": ["3b", "7b"],
                                                  "about": "Synthetic model for checking the desktop layout."},
                                                 {"name": "review-medium", "sizes": ["8b", "14b"],
                                                  "about": "A second synthetic model with selectable download sizes."}]})
        if path == "/api/prefs":
            return JSONResponse({"harnesses": [{"id": "review", "label": "Review fixture"}],
                                 "unusable": [], "chosen": {"preferred_harness": "review"}})
        if path == "/api/local-models":
            return JSONResponse({"ready": False, "servers": [], "models": []})
        if path == "/api/packs/updates":
            return JSONResponse({"items": [], "available": []})
        if request.method == "POST" and path not in {"/api/chat/threads", "/api/compare-drafts"}:
            return JSONResponse({"detail": "Fixture: agent and provider actions are disabled."},
                                status_code=422)
        return await call_next(request)

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP)
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    ready = {"url": f"http://127.0.0.1:{listener.getsockname()[1]}",
             "source": str(chat.__file__)}
    (scratch / "ready.json").write_text(json.dumps(ready), encoding="utf-8")
    print(ready["url"], flush=True)
    uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="warning")).run(
        sockets=[listener]
    )


if __name__ == "__main__":
    main()
