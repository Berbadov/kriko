"""What one turn costs on each of the five agent planes, and what dominates it.

The five planes are the four coding-agent CLIs Kriko drives (`claude-code`,
`antigravity-cli`, `codex`, `mistral-vibe`) and this machine's own model. A
turn's wall clock is mostly the vendor's inference, which Kriko cannot change
and this script does not try to. What it measures is everything *Kriko* pays
before and around that inference, because that is the part a change here can
move:

* the plane decision (`tasks.default_plane`), which probes this machine's
  model server and every installed CLI;
* the launch vector (`harness.command_for`), which spawns the CLI's own
  `--help` and asks its model list, both real subprocesses;
* the brief the plane is handed, in characters, and what it carries;
* for the local plane, the whole orchestration of a Quick Look with the model
  stubbed — query planning, page fitting, the evidence blocks, the grounding
  pass — which is the same code path a real answer runs on, with no network.

Offline by default and by design: the local plane runs against an in-file
model, and a CLI plane is measured up to the point of handing it a prompt.
`--live` additionally sends one real turn per installed CLI, which needs a
signed-in account and the internet; it is never part of a measurement anyone
compares across machines.

    python tools/bench_agent_planes.py --runs 5
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app import localplane, quicklook  # noqa: E402
from app.providers import harness, local_agent  # noqa: E402
from app.providers.local_pipeline import (  # noqa: E402
    EXTRACT_SCHEMA, GROUP_SCHEMA, IDENTITY_SCHEMA, LANGUAGE_CHECK_SCHEMA,
    LANGUAGE_SCHEMA, PAIR_SCHEMA, RENDER_SCHEMA, SOURCE_KIND_SCHEMA, VERIFY_SCHEMA,
)

PRODUCT = "Bosch GSR 18V-55"
PAGE = "https://reviews.example.org/gsr-18v"
PAGE_TEXT = (
    "The GSR 18V-55 has a well-documented failure in its gearbox: owners "
    "report that the second gear starts slipping after roughly a year of "
    "regular use, and the replacement gearbox is not cheap. A second, less "
    "common report is that the electronic brake stops working when the tool "
    "gets hot, which Bosch has acknowledged in a service bulletin. The chuck "
    "is metal and has not been the subject of a recall. Battery runtime is "
    "about forty minutes with the 2.0 Ah pack, and the tool weighs 1.3 kg."
)

_STAGES = ((EXTRACT_SCHEMA, "extract"), (VERIFY_SCHEMA, "verify"),
           (SOURCE_KIND_SCHEMA, "source"), (RENDER_SCHEMA, "render"),
           (LANGUAGE_SCHEMA, "language"), (LANGUAGE_CHECK_SCHEMA, "language_check"),
           (GROUP_SCHEMA, "group"), (PAIR_SCHEMA, "pair"), (IDENTITY_SCHEMA, "identity"))


def _stage(schema: dict) -> str:
    for shape, name in _STAGES:
        if schema == shape:
            return name
    return "plan" if "queries" in schema.get("properties", {}) else "other"


class ScriptedModel:
    """A local model with no sockets: answers each stage by its schema.

    The Quick Look pipeline asks the model for nine different things; anything
    that answered them all identically would measure a pipeline that took a
    different path through its repairs. This answers each stage the way the
    real model does, so the measured run is the real run.
    """

    max_tokens = 1024
    last_finish_reason = "stop"

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self.prompts: list[tuple[str, int]] = []

    def prompt_chars_allowed(self) -> int:
        return 12000

    def context_tokens(self) -> int:
        return 4096

    def stages(self) -> list[str]:
        return [stage for stage, _ in self.calls]

    def json(self, prompt, schema):
        stage = _stage(schema)
        self.calls.append((stage, len(prompt)))
        self.prompts.append((stage, len(prompt)))
        return json.dumps(self._answer(stage), ensure_ascii=False)

    def __call__(self, prompt):
        return self.json(prompt, {})

    def _answer(self, stage: str):
        if stage == "identity":
            return {"canonical_name": "", "aliases": [], "variant": "", "identifiers": [],
                    "unknowns": [], "evidence": [], "brand": "", "item": "",
                    "item_terms": [], "fits": ""}
        if stage == "language":
            return {"language": "en"}
        if stage == "language_check":
            return {"matches": True}
        if stage == "plan":
            return {"queries": ["Bosch GSR 18V-55 gearbox failure"]}
        if stage == "extract":
            return {"category": "cordless drill", "pack": "", "pack_identity": {},
                    "risks": [{"title": "Gearbox slip", "why": "Second gear slips.",
                               "check": "Ask about the gearbox.", "severity": "high",
                               "evidence": ["E1"]}],
                    "specs": []}
        if stage == "verify":
            return {"evidence_kind": "problem", "support": "supported", "identity": "match"}
        if stage == "source":
            return {"kind": "problem"}
        if stage == "render":
            return {"title": "Gearbox slip", "why": "Second gear slips.",
                    "check": "Ask about the gearbox."}
        if stage == "group":
            return {"groups": []}
        if stage == "pair":
            return {"same_failure": False}
        return {}


def _searcher(hits: list[dict]):
    def search(query, limit, **_options):
        return list(hits)
    return search


def _reader(pages: dict[str, str]):
    def fetch(url, **_options):
        return pages.get(url, "")
    return fetch


def measure(function, runs: int) -> list[float]:
    values = []
    for _ in range(runs):
        began = time.perf_counter()
        function()
        values.append((time.perf_counter() - began) * 1000)
    return values


def _summary(values: list[float]) -> dict:
    return {"runs": len(values),
            "median_ms": round(statistics.median(values), 3),
            "min_ms": round(min(values), 3),
            "max_ms": round(max(values), 3)}


def _first(values: list[float]) -> dict:
    """The first sample, for a measurement whose cost is paid once.

    `--help` and a model listing are asked once and cached, so the median of
    repeated calls reports the *cache* and not the cost. The first call is the
    number a reader waits for.
    """
    return {"runs": 1, "median_ms": round(values[0], 3),
            "min_ms": round(values[0], 3), "max_ms": round(values[0], 3)}


# ── the local plane ─────────────────────────────────────────────────────────

class _LoopbackModel:
    """A model server on this machine's own loopback, answering like a real one.

    Everything but the weights: a real HTTP server, a real socket, the real
    OpenAI-compatible request and response, and the real `urllib` transport in
    `app/providers/network.py`. What it replaces is only the part Kriko cannot
    change — how long a model takes to think — so the figure this produces is
    the local plane's own turn cost and nothing else.
    """

    def __init__(self, scripted: ScriptedModel) -> None:
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                self._send(200, {"object": "list", "data": [{"id": "scripted"}]})

            def do_POST(self) -> None:
                size = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(size) or b"{}")
                schema = ((body.get("response_format") or {}).get("json_schema")
                          or {}).get("schema") or {}
                owner.requests += 1
                self._send(200, {"choices": [{"message": {
                    "content": scripted.json(json.dumps(body), schema)}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1,
                              "total_tokens": 2}})

            def _send(self, status: int, payload) -> None:
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.requests = 0
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def bench_local(runs: int) -> dict:
    """One Quick Look on this machine's model, over a real loopback socket."""
    hits = [{"url": PAGE, "title": "GSR 18V-55 review"}]
    pages = {PAGE: PAGE_TEXT}
    briefs: dict[str, int] = {}
    stages: dict[str, int] = {}

    def one_turn() -> None:
        model = ScriptedModel()
        asker = local_agent.LocalAsker(
            model, model, _searcher(hits), _reader(pages),
            model="scripted", search_provider="stub", url="http://127.0.0.1:1")
        asker.ask_quick(PRODUCT, page={"facts": {"ld:name": PRODUCT}})
        briefs["prompt_chars"] = sum(size for _, size in model.prompts)
        for name, size in model.prompts:
            stages[name] = stages.get(name, 0) + size

    started = time.perf_counter()
    one_turn()
    cold_ms = (time.perf_counter() - started) * 1000
    values = measure(one_turn, runs)
    return {"cold_ms": round(cold_ms, 3), "warm": _summary(values),
            "prompt_chars": briefs.get("prompt_chars", 0),
            "prompt_chars_by_stage": stages,
            "model_calls": len(stages)}


def bench_local_socket(runs: int) -> dict:
    """The same Quick Look against a loopback HTTP server, sockets and all."""
    from app.providers import fetch, local_asker, openserp

    model = ScriptedModel()
    server = _LoopbackModel(model)
    hits = [{"url": PAGE, "title": "GSR 18V-55 review"}]
    pages = {PAGE: PAGE_TEXT}
    real_searcher, real_reader = openserp.searcher, fetch.reader
    openserp.searcher = lambda *_a, **_k: _searcher(hits)
    fetch.reader = lambda **_k: _reader(pages)
    try:
        def one_turn() -> None:
            asker = local_asker(base_url=server.url, serving_name="scripted",
                                search_base_url="http://127.0.0.1:1")
            asker.ask_quick(PRODUCT, page={"facts": {"ld:name": PRODUCT}})

        one_turn()  # imports and the first opener
        values = measure(one_turn, runs)
        server.requests = 0
        one_turn()
        requests = server.requests
    finally:
        openserp.searcher, fetch.reader = real_searcher, real_reader
        server.close()
    return {"one_turn": _summary(values), "loopback_requests": requests,
            "per_request_ms": round(statistics.median(values) / max(1, requests), 3)}


# ── the CLI planes ──────────────────────────────────────────────────────────

def _brief_for(one: harness.Harness) -> str:
    """The brief this plane's Quick Look path hands it, built for real."""
    return quicklook.brief(PRODUCT, max_sources=3, language="auto")


def bench_cli(one: harness.Harness, runs: int) -> dict:
    """What Kriko pays for one turn on `one`, up to the moment of the prompt."""
    harness.forget_located()
    locate_cold = measure(lambda: harness.forget_located() or harness.locate(one), runs)
    locate_warm = measure(lambda: harness.locate(one), runs)

    # `command_for` is the launch vector. It asks the CLI's own `--help` (a real
    # subprocess) when the capability cache is cold, which is what a first turn
    # after a restart pays.
    executable = harness.locate(one) or one.executable
    harness._HELP.pop(executable, None)
    harness._DECLARED.pop(executable, None)
    declared_cold = measure(lambda: harness.declared(executable), runs)
    harness._HELP.pop(executable, None)
    harness._DECLARED.pop(executable, None)
    declared_warm = measure(lambda: harness.declared(executable), runs)
    declared = harness.declared(executable)

    command_ms = measure(lambda: harness.command_for(one, max_documents=3), runs)
    models_ms = measure(lambda: harness.models_for(one, fresh=True, behind=True), runs)
    brief_ms = measure(lambda: _brief_for(one), runs)
    harness.forget_located()
    return {
        "id": one.id,
        "label": one.label,
        "installed": bool(harness.locate(one)),
        "unusable": one.unusable,
        "protocol": one.protocol,
        "resident": one.protocol in harness.RESIDENT_PROTOCOLS,
        "locate_cold": _first(locate_cold),
        "locate_warm": _summary(locate_warm),
        "declared_cold": _first(declared_cold),
        "declared_warm": _summary(declared_warm),
        "declares": len(declared),
        "command_for": _summary(command_ms),
        "models_for_fresh": _first(models_ms),
        "models": len(harness.models_for(one)),
        "brief": _summary(brief_ms),
        "brief_chars": len(_brief_for(one)),
    }


def bench_plane_choice(runs: int) -> dict:
    """`default_plane` — the probe every job start pays before anything runs.

    Measured twice: `cold` asks the machine afresh every time (the worst case,
    which is what a first job after a restart pays), `warm` asks it three times
    in a row the way one turn does — the plane decision, the readiness gate and
    the run's own plan.
    """
    from app.providers import local_discovery
    from app.web import tasks

    def cold() -> None:
        local_discovery.forget_discovery()
        tasks.default_plane(None)

    values = measure(cold, runs)
    local_discovery.forget_discovery()
    tasks.default_plane(None)  # one real probe, so `warm` measures the repeats
    warm = measure(lambda: tasks.default_plane(None), runs)
    return {"cold": _summary(values), "warm": _summary(warm),
            "reason": tasks.default_plane(None)[1]}


def bench_loopback_request(runs: int) -> dict:
    """What one request to this machine costs through the app's HTTP transport.

    The local plane's search, page read and every model call go through
    `app/providers/network.py`, so this is the floor under a local turn that is
    not the model's own answering time.
    """
    from app.providers import network

    server = _LoopbackModel(ScriptedModel())
    url = server.url + "/v1/models"

    def one() -> None:
        with network.urlopen(url, timeout=5) as response:
            response.read()

    try:
        values = measure(one, max(20, runs))
    finally:
        server.close()
    return {"request": _summary(values)}


def bench_local_probe(runs: int) -> dict:
    """The loopback round-trips one readiness question costs."""
    from app.providers import local_discovery

    calls = {"count": 0}
    real = local_discovery._get

    def counted(url, timeout, **kwargs):
        calls["count"] += 1
        return real(url, timeout, **kwargs)

    def cold() -> None:
        local_discovery.forget_discovery()
        localplane.is_ready(None)

    local_discovery._get = counted
    try:
        values = measure(cold, runs)
        per_call = calls["count"] / max(1, runs)
    finally:
        local_discovery._get = real
    return {"is_ready": _summary(values), "http_requests_per_call": round(per_call, 2)}


def bench_briefs(runs: int) -> dict:
    """What each brief carries, in characters, against a filled knowledge store.

    The context claim is about *size and content*, not about wall clock, so the
    number that matters here is how much of the store reaches the agent. A brief
    that carries the whole catalogue or a whole research record is slow on every
    plane and worse than one that carries the right rows.
    """
    import tempfile

    from app import categorizer
    from app.web import tasks
    from kriko.store.db import connect

    tmp = Path(tempfile.mkdtemp()) / "k.sqlite"
    store = connect(tmp)
    for index in range(12):
        pack_id = f"cat.{index:02d}"
        store.execute(
            "INSERT INTO packs (pack_id, name, version, schema_version, built_at,"
            " content_digest, enabled, installed_at) VALUES (?,?,?,?,?,?,?,?)",
            (pack_id, f"Category {index:02d} appliances", "1", 1, "2026-09-01", "d", 1,
             "2026-09-01"))
        for term in range(14):
            store.execute(
                "INSERT INTO terms (pack_id, term_id, role, label_json) VALUES (?,?,?,?)",
                (pack_id, f"term_{term:02d}",
                 "attribute" if term % 2 else "subject_kind",
                 json.dumps({"en": f"attribute {index} {term}"})))
        for row in range(10):
            subject = f"s{index}_{row}"
            store.execute(
                "INSERT INTO subjects (subject_id, pack_id, kind, label) VALUES (?,?,?,?)",
                (subject, pack_id, "product", f"Category {index:02d} product {row}"))
    store.commit()
    store.close()

    profiles = categorizer.installed_catalogs(tmp)
    catalogue = categorizer.choice_block(profiles)
    product = PRODUCT
    page = {"facts": {"ld:name": product, "brand": "Bosch"},
            "description": "A cordless drill."}
    attributes = "\n".join(f"* attribute {index}" for index in range(40))
    stored = {
        "label": product,
        "response": {
            "category": "cordless drill", "assumed": "the 55 model",
            "diagnostic": {"message": "3 of 7 pages were readable."},
            "coverage": {"status": "partial", "pages_read": 7, "pages_relevant": 3,
                         "pages_extracted": 1, "publishers_read": 4},
            "identity": {"brand": "Bosch", "model": "GSR 18V-55"},
            "listing": {"url": "https://shop.example/d/1",
                        "facts": {f"fact {index}": "value " * 6 for index in range(24)},
                        "description": "Seller description " * 40},
            "claims": [{"title": f"Risk {index}", "body": "It fails. " * 20,
                        "advice": "Check it.", "severity": "high",
                        "sources": [{"url": f"https://forum.example/{index}",
                                     "quote": "A quote that is a sentence. " * 8}]}
                       for index in range(8)],
            "specs": [{"name": f"Spec {index}", "value": "1.5 kg",
                       "url": "https://a.example/x", "quote": "1.5 kg"}
                      for index in range(6)],
            "context": {f"k{index}": "v" for index in range(8)},
            "evidence_pages": [{"url": f"https://p.example/{index}", "excerpt": "x" * 700}
                               for index in range(5)],
        },
    }
    previous = [{"state": "succeeded",
                 "params": {"question": "Is it quiet? " * 20},
                 "result": {"answer": "It is quiet. " * 300}} for _ in range(6)]
    from app import followup

    return {
        "quicklook_no_catalogue": len(quicklook.brief(product, max_sources=3)),
        "quicklook_with_catalogue": len(quicklook.brief(
            product, page=page, packs=catalogue, attributes=attributes, max_sources=3)),
        "quicklook_shortlist": len(quicklook.brief(
            product, page=page, packs=categorizer.choice_block(
                categorizer.shortlist(product, page, profiles)),
            attributes=attributes, max_sources=3)),
        "catalogue_rows_shown": len(categorizer.shortlist(product, page, profiles)),
        "catalogue_rows_installed": len(profiles),
        "follow_up_brief": len(followup.web_brief(
            "Is the seller reliable?", product=product,
            context="What the saved check recorded about this product "
                    "(a starting point, not the limit):\n"
                    + tasks._follow_up_context(stored, "Is the seller reliable?", previous),
            kind="seller")),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--live", action="store_true",
                        help="also send one real turn per installed CLI (needs an account)")
    args = parser.parse_args()

    report: dict = {"product": PRODUCT, "runs": args.runs, "planes": {}, "shared": {}}
    report["shared"]["local_probe"] = bench_local_probe(args.runs)
    report["shared"]["loopback_request"] = bench_loopback_request(args.runs)
    report["shared"]["plane_choice"] = bench_plane_choice(args.runs)
    report["shared"]["briefs"] = bench_briefs(args.runs)
    report["planes"]["local"] = bench_local(args.runs)
    report["planes"]["local_socket"] = bench_local_socket(args.runs)
    for one in harness.KNOWN:
        report["planes"][one.id] = bench_cli(one, args.runs)

    if args.live:
        report["live"] = live_turns(args.runs)

    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    _print(report)
    return 0


def live_turns(runs: int) -> dict:
    """One real turn per installed CLI. Needs a signed-in account and internet."""
    from app.providers import harness_researcher

    out: dict = {}
    for one in harness.available():
        try:
            researcher = harness_researcher(preferred=one.id, timeout=180.0)
            values = measure(
                lambda researcher=researcher: researcher.ask_quick(PRODUCT), runs)
            out[one.id] = {"ask_quick": _summary(values),
                           "stages": getattr(researcher, "metrics", [])}
        except Exception as error:  # noqa: BLE001 - a vendor failure is a datum
            out[one.id] = {"error": f"{type(error).__name__}: {error}"}
    return out


def _print(report: dict) -> None:
    shared = report["shared"]
    print(f"product: {report['product']}   runs per figure: {report['runs']}")
    print()
    probe = shared["local_probe"]
    print(f"local readiness probe   {probe['is_ready']['median_ms']:9.2f} ms  "
          f"({probe['http_requests_per_call']} loopback requests per call)")
    print(f"one loopback request    {shared['loopback_request']['request']['median_ms']:9.2f} ms")
    choice = shared["plane_choice"]
    print(f"default_plane cold      {choice['cold']['median_ms']:9.2f} ms  "
          f"warm {choice['warm']['median_ms']:7.2f} ms  -> {choice['reason'][:60]}")
    briefs = shared["briefs"]
    print(f"quick-look brief        {briefs['quicklook_shortlist']:9d} c  "
          f"(whole catalogue {briefs['quicklook_with_catalogue']} c, nothing "
          f"{briefs['quicklook_no_catalogue']} c; "
          f"{briefs['catalogue_rows_shown']} of {briefs['catalogue_rows_installed']} rows)")
    print(f"follow-up brief         {briefs['follow_up_brief']:9d} c  "
          "(identity, recorded risks with their pages, the question)")
    print()
    print(f"{'plane':18s} {'turn/prep':>10s} {'cold':>10s} {'brief':>8s}  what dominates")
    print("-" * 82)
    local = report["planes"]["local"]
    print(f"{'local':18s} {local['warm']['median_ms']:9.2f}ms {local['cold_ms']:9.2f}ms "
          f"{local['prompt_chars']:7d}c  "
          f"{local['model_calls']} model calls, {local['prompt_chars']} prompt chars")
    sock = report["planes"]["local_socket"]
    print(f"{'local (sockets)':18s} {sock['one_turn']['median_ms']:9.2f}ms {'':>9s} {'':>8s}  "
          f"{sock['loopback_requests']} loopback requests, "
          f"{sock['per_request_ms']:.2f} ms each")
    for one in harness.KNOWN:
        row = report["planes"][one.id]
        total = (row["command_for"]["median_ms"] + row["models_for_fresh"]["median_ms"])
        dominates = (f"locate {row['locate_cold']['median_ms']:.1f}ms, "
                     f"--help {row['declared_cold']['median_ms']:.1f}ms, "
                     f"models {row['models_for_fresh']['median_ms']:.1f}ms")
        state = "" if row["installed"] else " (not installed)"
        print(f"{one.id:18s} {total:9.2f}ms {row['declared_cold']['median_ms']:9.2f}ms "
              f"{row['brief_chars']:7d}c  {dominates}{state}")


if __name__ == "__main__":
    raise SystemExit(main())
