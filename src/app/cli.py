"""kriko — the command line.

    kriko pack build packs/drill
    kriko install dist/drill.kpack
    kriko packs
    kriko lookup --kind product brand=makita model=DHP484 --ctx usage_hours=800
    kriko disable org.kriko.drill
    kriko uninstall org.kriko.drill

The reader's whole loop with no server, no account and no network: build a pack
or fetch someone else's, install it, ask it things, remove it when it stops
earning its place. Everything lives in ~/.kriko unless --store says otherwise.

Two rules keep every invocation fast, the way the harness binary is fast — one
short process, no server behind it:

1. Nothing heavy is imported until the command that needs it has been named.
   `--version`, `--help` and a parse error cost the interpreter and argparse
   and nothing else; `app.agentbench`'s multi-second import tree is only built
   when the command is actually `agent-bench` (see `_peek_command`).
2. Read-only commands that used to attach to an engine or start one now read
   the files directly (`app.clidirect`): `prefs`, `costs`, `sites list`,
   `verify --list`, `drafts list/show` and `operations` answer from
   `app.sqlite` beside `--store` in this process, so the answer never depends
   on whether some other engine happened to be running. Commands that change
   state (writes, jobs) still go through an engine over HTTP.

Every command also takes `--json`: the same answer as one JSON document on
stdout, so a script never has to scrape the human text. The research door
(`agenda`, `brief`, `submit`, `loopscore`) prints JSON always, as it always
has.
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path


def _kv(pairs: list[str]) -> dict:
    """Parse `key=value` arguments, keeping numbers numeric."""
    out: dict[str, int | float | str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"expected key=value, got {pair!r}")
        key, _, value = pair.partition("=")
        try:
            out[key] = int(value)
        except ValueError:
            try:
                out[key] = float(value)
            except ValueError:
                out[key] = value
    return out


def _emit(args, payload, render) -> int:
    """The one output door. `--json` prints the payload as JSON; without it
    `render()` draws the human text it always drew. Every command funnels
    through here, so machine output is stable and text output is unchanged."""
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    else:
        render()
    return 0


def _add_json(p: argparse.ArgumentParser) -> None:
    # SUPPRESS so a subcommand that does not repeat the flag keeps the
    # top-level `kriko --json <command>` answer.
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                   help="print the answer as one JSON document")


def cmd_packs(args, store) -> int:
    from kriko.store import packstore

    rows = packstore.installed_packs(store)
    payload = {"packs": [{**dict(row), "enabled": bool(row["enabled"])}
                         for row in rows]}

    def render() -> None:
        if not rows:
            print("no packs installed — try: kriko install <file.kpack>")
            return
        print(f"{'PACK':<28} {'VERSION':<10} {'STATE':<9} {'TRUST':>6}  NAME")
        for row in rows:
            state = "enabled" if row["enabled"] else "disabled"
            print(f"{row['pack_id']:<28} {row['version']:<10} {state:<9} "
                  f"{row['trust_weight']:>6.2f}  {row['name']}")

    return _emit(args, payload, render)


def cmd_install(args, store) -> int:
    from kriko.store import packstore

    pack_id = packstore.install(store, args.path)
    counts = {
        table: store.execute(
            f"SELECT COUNT(*) FROM {table} WHERE pack_id = ?", (pack_id,)).fetchone()[0]
        for table in ("subjects", "claims", "evidence")
    }
    payload = {"pack_id": pack_id, "counts": counts}

    def render() -> None:
        print(f"installed {pack_id}: "
              + ", ".join(f"{v} {k}" for k, v in counts.items()))

    return _emit(args, payload, render)


def cmd_uninstall(args, store) -> int:
    from kriko.store import packstore

    packstore.uninstall(store, args.pack_id)
    payload = {"uninstalled": args.pack_id}
    return _emit(args, payload,
                 lambda: print(f"uninstalled {args.pack_id} — every other pack is untouched"))


def cmd_enable(args, store) -> int:
    from kriko.store import packstore

    packstore.set_enabled(store, args.pack_id, not args.disable)
    payload = {"pack_id": args.pack_id, "enabled": not args.disable}
    return _emit(args, payload,
                 lambda: print(f"{args.pack_id}: {'disabled' if args.disable else 'enabled'}"))


def cmd_build(args, store) -> int:
    # Imported here: the builder pulls in yaml and tomllib, which a reader who
    # only ever installs packs should not pay for on every command.
    import importlib

    from kriko.pack.build import build as generic_build, digest_of

    root = Path(args.root)
    out = Path(args.out) if args.out else Path("dist") / f"{root.name}.kpack"

    # A pack may ship its own builder (packs/<name>/build.py) for data that
    # needs generating rather than transcribing — see docs/PACK_CONTRACT.md.
    # Pointing the generic builder at such a pack "succeeds" and produces a
    # pack with nothing in it, so the pack's own builder takes precedence
    # when present. Same convention as
    # test_every_pack_in_the_repo_builds_and_is_not_empty.
    own_builder = (root / "build.py").exists()
    stats = None
    if own_builder:
        # The builder is `packs.<name>.build`, imported from the directory
        # that holds `packs/`, so `kriko build packs/<name>` works from the
        # checkout without PYTHONPATH.
        holder = str(root.resolve().parent.parent)
        if holder not in sys.path:
            sys.path.insert(0, holder)
        module = importlib.import_module(f"packs.{root.name}.build")
        result = module.build(out)
        if isinstance(result, tuple):
            out, report = result
            if isinstance(report, dict):
                stats = report.get("stats", report)
        else:
            out = result
    else:
        generic_build(root, out)

    # Read-only and plain: the store's connector would switch the finished
    # file to WAL and leave -wal/-shm beside the .kpack that gets shared.
    conn = sqlite3.connect(f"file:{Path(out).resolve().as_posix()}?mode=ro", uri=True)
    try:
        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("subjects", "claims", "evidence")
        }
    finally:
        conn.close()

    digest = digest_of(out)
    payload = {"out": str(out), "digest": digest, "counts": counts,
               "stats": stats or {}}

    def render() -> None:
        print(f"built {out}  digest {digest[:16]}")
        print("  " + ", ".join(f"{v} {k}" for k, v in counts.items()))
        if stats:
            for key, value in sorted(stats.items()):
                print(f"  {key:34} {value}")

    if not counts["subjects"] and not counts["claims"]:
        print(
            f"kriko: {out} has no subjects and no claims — it cannot answer "
            "anything and will not be written.\n"
            "  If this is a legitimate intermediate state (a pack under "
            "authoring), pass --force to write it anyway.",
            file=sys.stderr,
        )
        if not args.force:
            out.unlink(missing_ok=True)
            return 1

    return _emit(args, payload, render)


def _claim_json(claim) -> dict:
    return {
        "claim_id": claim.claim_id,
        "pack_id": claim.pack_id,
        "subject_id": claim.subject_id,
        "subject_label": claim.subject_label,
        "kind": claim.kind,
        "domain": claim.domain,
        "severity": claim.severity,
        "detection": claim.detection,
        "title": claim.title,
        "advice": claim.advice,
        "relevance": claim.relevance,
        "trust": claim.trust,
        "disputed": claim.disputed,
        "via": claim.via,
        "why": list(claim.why),
        "sources": [
            {"url": s.url, "tier": s.tier, "stance": s.stance}
            for s in claim.sources
        ],
    }


def cmd_lookup(args, store) -> int:
    from dataclasses import asdict

    from kriko.lookup import lookup
    from kriko.lookup.query import Query

    result = lookup(store, Query(
        kind=args.kind,
        identity=_kv(args.identity),
        context=_kv(args.ctx or []),
        lang=args.lang,
        limit=args.limit,
    ))

    res = result.resolution
    payload = {
        "match": asdict(res),
        "coverage": result.coverage,
        "claims": [_claim_json(c) for c in result.claims],
    }

    def render() -> None:
        print(f"match: {res.method}  ({len(res.subject_ids)} subject(s))  "
              f"coverage: {result.coverage}")
        if res.notes:
            print(f"  {res.notes}")
        for flag in res.flags:
            print(f"  flag: {flag}")

        if not result.claims:
            print("\nno claims for this one.")
            return

        print()
        for n, claim in enumerate(result.claims, 1):
            mark = " [disputed]" if claim.disputed else ""
            print(f"{n}. [{claim.severity}] {claim.title}{mark}")
            print(f"   {claim.subject_label}  ·  {claim.domain}  · "
                  f"relevance {claim.relevance:.3f}")
            if claim.advice and args.verbose:
                print(f"   check: {claim.advice}")
            if args.verbose:
                for reason in claim.why:
                    print(f"   · {reason}")
                for source in claim.sources:
                    arrow = "×" if source.stance == "refutes" else "→"
                    print(f"   {arrow} [{source.tier}] {source.url}")
            print()

    return _emit(args, payload, render)


def _siblings(args) -> tuple[Path, Path]:
    """`app.sqlite` and the analyses log for the store this command opened.

    Derived beside the store, as `mcp_server` derives them, so `--store`
    pointed at a copy never writes into the reader's real history.
    `KRIKO_ANALYSES_LOG` still wins, because the app itself honours it.
    """
    import os

    from app import clidirect

    store_path = clidirect.store_path(args.store)
    app_state = store_path.parent / "app.sqlite"
    override = os.environ.get("KRIKO_ANALYSES_LOG")
    if override:
        return app_state, Path(override)
    if args.store:
        return app_state, store_path.parent / "logs" / "analyses.jsonl"
    from app.web.settings import default_analysis_log

    return app_state, Path(default_analysis_log())


def _agent_op(args, name: str, arguments: dict, body):
    """Run one research operation through the CLI door and print its JSON.

    Recorded in the operations feed exactly like an MCP call, under
    `door="cli"`, so the app shows a harness driving `kriko submit` the same
    way it shows one driving the MCP tool.
    """
    from app import operations

    app_state, _ = _siblings(args)
    with operations.record(app_state, door="cli", name=name,
                           arguments=arguments) as outcome:
        result = body()
        outcome["response"] = operations.summarise(result)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    return 0


def cmd_agenda(args, store) -> int:
    from app import agentops

    app_state, log_path = _siblings(args)
    return _agent_op(
        args, "research_agenda", {"pack_id": args.pack, "limit": args.limit},
        lambda: agentops.agenda(store, app_state_path=app_state, log_path=log_path,
                                pack_id=args.pack, limit=args.limit),
    )


def cmd_brief(args, store) -> int:
    from app import agentops

    app_state, _ = _siblings(args)
    return _agent_op(
        args, "research_brief",
        {"subject_id": args.subject_id, "pack_id": args.pack, "mode": args.effort},
        lambda: agentops.brief(store, args.subject_id, args.pack,
                               effort=args.effort, app_state_path=app_state),
    )


def cmd_loopscore(args, store) -> int:
    """`kriko loopscore SUBJECT --pack P`: how well the research loop is running.

    The agent planes are scored by the benches; the *loop* — submit, read
    the gaps, follow up — is scored here, off the submission log every door
    writes. The metrics are the loop's own: pass rate on the first submit
    against the last (did the verdicts teach it anything), findings kept per
    search, and how much of what it ran was its own work rather than a
    re-roll of the pack's seeds.
    """
    from app import agentops, loopmetrics
    from kriko.research import plan_task

    app_state, _ = _siblings(args)
    runs = agentops.prior_runs(app_state, args.subject_id, args.pack,
                               limit=args.limit)
    seeds = plan_task(store, args.subject_id, args.pack).rendered_queries()
    print(json.dumps(loopmetrics.score(runs, seeds), indent=2, ensure_ascii=False))
    return 0


def cmd_submit(args, store) -> int:
    """`kriko submit SUBJECT --pack P findings.json` (or `-` for stdin).

    The file is either a list of findings or `{"findings": [...], "queries":
    [...]}` — the second shape is `submit_findings`' own arguments, so an
    agent that learnt the MCP tool writes the same JSON here.
    """
    from app import agentops

    raw = sys.stdin.read() if args.findings == "-" else Path(args.findings).read_text(
        encoding="utf-8")
    payload = json.loads(raw)
    if isinstance(payload, list):
        findings, queries = payload, list(args.query or [])
    elif isinstance(payload, dict) and isinstance(payload.get("findings"), list):
        findings = payload["findings"]
        queries = list(payload.get("queries") or []) + list(args.query or [])
    else:
        raise ValueError("findings must be a JSON list, or an object with a "
                         "'findings' list")
    app_state, _ = _siblings(args)
    return _agent_op(
        args, "submit_findings",
        {"subject_id": args.subject_id, "pack_id": args.pack,
         "findings": findings, "queries": queries},
        lambda: agentops.submit(store, app_state_path=app_state, door="cli",
                                subject_id=args.subject_id, pack_id=args.pack,
                                findings=findings, queries=queries or None),
    )


def cmd_tui(args, store) -> int:
    """The operator console. Imported here, not at module scope.

    `kriko lookup` must not pay for a terminal UI it will never draw, and
    `app.tui` reaches `app.web` (to start an engine when none is running),
    which is a whole FastAPI app's import cost on a command that answers a
    question about a car in milliseconds.
    """
    from app.tui import main as run_tui

    return run_tui(url=args.url, allow_start=not args.no_start)


def cmd_agent_bench(args, store) -> int:
    """Grade agents on the fixed task suite (`app/agentbench`)."""
    if not hasattr(args, "profile"):
        # Reached only if the parser was built without this command's own
        # arguments, which `_peek_command` prevents; a guard, not a path.
        print("kriko: agent-bench arguments were not built", file=sys.stderr)
        return 1
    from app.agentbench.cli import run

    return run(args)


def cmd_model_bench(args, store) -> int:
    """Measure models on the controlled corpus (`app/modelbench`).

    Delegated rather than re-implemented: `python -m app.modelbench` is the
    complete command — `list`, `plan`, `run`, with the report files — and a
    second copy of those flags here would drift from it. The pass-through keeps
    one command with two spellings, which is what a person pasting a result into
    a chat actually needs.
    """
    from app.modelbench.__main__ import main as model_bench_main

    rest = [one for one in getattr(args, "rest", [])]
    if not rest:
        model_bench_main(["--help"])
        return 0
    return model_bench_main(rest)


def cmd_bench(args, store) -> int:
    """Measure the planes against the same cases (B111).

    In the terminal as well as in the app, because this is the command whose
    output is an *argument* — "the harness plane refuses four findings in five
    and the API plane one in three" is a sentence somebody has to be able to
    paste. It runs in this process rather than submitting a job: a benchmark
    watched by nobody is a benchmark nobody trusts, and the reader running it
    from a terminal is already watching.
    """
    from app import bench as bench_mod
    from app.web import state
    from app.web.settings import Settings

    # The app's own database as a *sibling of the store*, the way
    # `mcp_server._app_state_path` derives it. That is what makes `--store`
    # self-contained: a measurement against a store somewhere else must not
    # land in the reader's real history, and a benchmark is exactly the thing
    # someone runs against a copy.
    store_path = Path(args.store) if args.store else None
    settings = (
        Settings(
            store_path=store_path,
            app_state_path=store_path.parent / "app.sqlite",
            analysis_log_path=store_path.parent / "logs" / "analyses.jsonl",
        )
        if store_path
        else Settings()
    )
    planes = [one for one in (args.plane or []) if one] or bench_mod.planes_available(
        settings
    )
    if not planes:
        print("no plane can run here: install a coding-agent CLI, or add API keys")
        return 1
    # The fixed, versioned set first (B185, D6); a named pack's own cases
    # still run with --pack, so an author can measure their own bar.
    from app import benchcases

    found = benchcases.case_rows(args.cases, getattr(args, "suite", "precision"))
    if not found:
        found = bench_mod.cases(store, pack_id=args.pack or "", limit=args.cases)
    if not found:
        print("no subjects installed, so there is nothing to measure")
        return 1

    conn = state.connect(settings.app_state_path)
    try:
        for case in found:
            for plane in planes:
                for protocol in (args.protocol or [""]):
                    row = bench_mod.run_case(
                        settings,
                        case,
                        plane=plane,
                        protocol=protocol,
                        max_documents=args.documents,
                        budget_usd=args.budget,
                    )
                    state.record_bench(conn, row)
                    label = f"{plane}/{protocol}" if protocol else plane
                    if row.get("error"):
                        print(f"{label:14} {row['subject'][:32]:32} "
                              f"failed: {row['error'][:50]}")
                    else:
                        print(
                            f"{label:14} {row['subject'][:32]:32} "
                            f"{row.get('accepted', 0):>3} kept "
                            f"{row.get('refused', 0):>3} refused "
                            f"{(row.get('ms') or 0) / 1000:>6.1f}s "
                            + (f"{row['tokens']:>8} tok" if row.get("tokens") else "")
                        )
        graded = bench_mod.scored(state.bench_runs(conn))["groups"]
        if graded:
            print()
            print("against the pack's ground truth:")
            for line in graded:
                recall = "-" if line["recall"] is None else f"{line['recall']:.0%}"
                halluc = (
                    "-" if line["hallucination_rate"] is None
                    else f"{line['hallucination_rate']:.0%}"
                )
                interval = line["recall_interval"]
                print(
                    f"{line['plane']:8} {(line['model'] or '')[:20]:20} "
                    f"recall {recall:>5}"
                    + (f" ({interval[0]:.0%}-{interval[1]:.0%})" if interval else "")
                    + f"  hallucinated {halluc:>5}  over {line['runs']} run(s)"
                )
        print()
        # How each plane failed, not only how often (B124): a plane that fails
        # the same way every time is being mis-used, not having bad luck.
        for line in bench_mod.verdict(state.bench_runs(conn))["planes"]:
            if not line["failed"]:
                continue
            classes = ", ".join(
                f"{name} x{count}" for name, count in sorted(line["classes"].items())
            )
            print(
                f"{line['plane']:8} {line['failed']}/{line['runs']} failed: {classes}"
                + (
                    "  — all the same way, which is a mis-use rather than bad luck"
                    if line["dominant_failure"]
                    else ""
                )
            )
        print()
        from app import protocols

        readout = protocols.readout(state.bench_runs(conn), state.bench_summary(conn))
        if readout:
            print()
            print("what each model would run with right now:")
            for line in readout:
                cost = "-" if line["usd_per_accepted_claim"] is None \
                    else f"${line['usd_per_accepted_claim']:.4f}"
                halluc = "—" if line["hallucination_rate"] is None \
                    else f"{line['hallucination_rate']:.0%}"
                print(
                    f"{line['model'][:24]:24} {line['protocol']:10} "
                    f"batch {line['batch_size']:>3}  ctx {line['context_chars']:>6}  "
                    f"{line['search_provider'] or '—':10} "
                    f"cost/claim {cost:>9}  hallucination {halluc}"
                )
                if line["note"]:
                    print(f"  {line['note']}")
        for line in state.bench_summary(conn):
            rate = "—" if line["acceptance"] is None else f"{line['acceptance']:.0%}"
            print(
                f"{line['plane']:8} {(line['model'] or '')[:20]:20} "
                f"{(line['protocol'] or '—'):9} "
                f"{line['runs']:>3} run(s)  {rate:>5} kept  "
                f"{(line['ms'] or 0) / 1000:>6.1f}s avg  "
                f"{line['failures']} failed"
            )
    finally:
        conn.close()
    return 0


def _connect_engine(args):
    """Attach to whichever engine is already serving, or start one of our own.

    Only the state-*changing* subcommands come through here now (prefs writes,
    site register/forget, verify, draft amend/build/install/discard): they
    enqueue jobs, and a job belongs to the engine that owns the app state.
    The read-only half reads the same files directly — see `app.clidirect`.
    """
    from app.tui.client import connect
    from app.web.settings import Settings

    store_path = Path(args.store) if getattr(args, "store", None) else None
    settings = (
        Settings(
            store_path=store_path,
            app_state_path=store_path.parent / "app.sqlite",
            analysis_log_path=store_path.parent / "logs" / "analyses.jsonl",
        )
        if store_path
        else None
    )
    return connect(
        getattr(args, "url", "") or "",
        allow_start=not getattr(args, "no_start", False),
        settings=settings,
    )


def _with_engine(args, fn) -> int:
    """Run `fn(engine)`, turning a failed attach or a failed call into a
    one-line message on stderr rather than a traceback — this is the door
    every state-changing command goes through."""
    from app.tui.client import EngineError

    try:
        engine = _connect_engine(args)
    except EngineError as exc:
        print(f"kriko: {exc}", file=sys.stderr)
        return 1
    try:
        return fn(engine)
    except EngineError as exc:
        print(f"kriko: {exc}", file=sys.stderr)
        return 1


def _render_prefs(data: dict) -> None:
    chosen = data.get("chosen", {})
    print("chosen now:")
    for key, value in sorted(chosen.items()):
        print(f"  {key:20} {value or '(default — whatever this machine offers)'}")
    print("\navailable harnesses:")
    for harness in data.get("harnesses", []):
        print(f"  {harness['id']:16} {harness.get('path', '')}")
    for harness in data.get("unusable", []):
        print(f"  {harness['id']:16} unusable: {harness.get('why', '')}")
    print("\nsearch providers:")
    for provider in data.get("search_providers", []):
        print(f"  {provider['id']:10} {'ready' if provider.get('ready') else 'no key set'}")


def _app_conn(args):
    """A read-only connection to the app state beside `--store`, or an empty
    in-memory one when the app has never run here — a read command must not
    create the reader's `app.sqlite` just to answer "nothing yet"."""
    from app import clidirect

    path = clidirect.app_state_path(args.store)
    conn = clidirect.open_readonly(path)
    if conn is None:
        conn = clidirect.scratch()
    return conn, path


def cmd_prefs(args, store) -> int:
    from app import clidirect

    if args.harness or args.model or args.search:
        # Only the flags actually given — sending the other two as `""`
        # would ask the engine to reset them to "whatever the machine
        # offers", which is not what `--model x` alone should do to an
        # already-chosen harness or search provider.
        fields = {}
        if args.harness:
            fields["preferred_harness"] = args.harness
        if args.model:
            fields["llm_model"] = args.model
        if args.search:
            fields["search_provider"] = args.search

        def run(engine) -> int:
            result = engine.write_prefs(**fields)
            return _emit(args, result, lambda: _render_prefs(result))

        return _with_engine(args, run)

    # The read half needs no engine: the same `prefs.choices` the router
    # serves, over a read-only connection to the file beside --store.
    conn, path = _app_conn(args)
    try:
        payload = clidirect.prefs(conn, path)
    finally:
        conn.close()
    return _emit(args, payload, lambda: _render_prefs(payload))


def _render_costs(data: dict) -> None:
    spent = data.get("spent", {})
    print(f"spent in the last {spent.get('days', '?')} day(s): "
          f"${spent.get('usd', 0):.2f} over {spent.get('runs', 0)} run(s)")
    for row in spent.get("planes", []):
        print(f"  {row.get('plane', ''):10} {row.get('llm', '') or '':20} "
              f"{row.get('runs', 0):>4} run(s)  ${row.get('usd', 0) or 0:.2f}")
    print("\nestimate for one more subject, by plane:")
    for plane, est in data.get("estimates", {}).items():
        usd = est.get("usd")
        print(f"  {plane:10} " + (f"${usd:.2f}" if usd is not None else "not enough history yet"))
    print("\nkeys:")
    for key in data.get("keys", []):
        print(f"  {key['id']:20} {'present' if key['present'] else 'missing':8} "
              f"{key['purpose']}")
    print(f"\n{data.get('balance', {}).get('note', '')}")


def cmd_costs(args, store) -> int:
    from app import clidirect

    conn, _ = _app_conn(args)
    try:
        payload = clidirect.costs(conn)
    finally:
        conn.close()
    return _emit(args, payload, lambda: _render_costs(payload))


def _render_sites(data: dict, action: str, host: str) -> None:
    if action == "list" or not action:
        registered = data.get("registered", [])
        requested = data.get("requested", [])
        if not registered and not requested:
            print("no sites registered or requested yet")
            return
        if registered:
            print("readable now:")
            for row in registered:
                print(f"  {row.get('site', row.get('host', '')):32} "
                      f"pack={row.get('pack_id', '')}")
        if requested:
            print("\nrequested (not yet readable):")
            for row in requested:
                print(f"  {row.get('host', ''):32} state={row.get('state', '')}")
        return
    if action == "register":
        print(f"job {data.get('job_id', '')} started: teaching this "
              f"installation to read {data.get('host', host)}")
        return
    if action == "forget":
        print(f"{host}: "
              + ("forgotten" if data.get("forgotten") else "was not registered"))


def cmd_sites(args, store) -> int:
    from app import clidirect

    if args.action in ("register", "forget") and not args.host:
        # Checked before any engine is attached: a missing argument is a
        # reader error, and starting a server to report it is the slow path.
        if args.action == "register":
            print("kriko: sites register needs a host, e.g. "
                  "\"kriko sites register example.com\"", file=sys.stderr)
        else:
            print("kriko: sites forget needs a host", file=sys.stderr)
        return 1

    if args.action == "list" or not args.action:
        conn, _ = _app_conn(args)
        try:
            payload = clidirect.sites(store, conn)
        finally:
            conn.close()
        return _emit(args, payload, lambda: _render_sites(payload, "list", ""))

    def run(engine) -> int:
        if args.action == "register":
            result = engine.register_site(args.host, url=args.url_for_site or "",
                                           pack_id=args.pack or "")
        elif args.action == "forget":
            result = engine.forget_site(args.host)
        else:
            print(f"kriko: unknown sites action {args.action!r}", file=sys.stderr)
            return 1
        return _emit(args, result, lambda: _render_sites(result, args.action, args.host))

    return _with_engine(args, run)


def cmd_verify(args, store) -> int:
    from app import clidirect

    if args.list:
        conn, _ = _app_conn(args)
        try:
            payload = clidirect.fact_checks(conn, verdict=args.verdict or "",
                                            limit=args.limit)
        finally:
            conn.close()

        def render() -> None:
            counts = payload.get("counts", {})
            print("counts: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
            for row in payload.get("items", []):
                print(f"  [{row.get('verdict', ''):10}] {row.get('title', '') or row.get('claim_id', '')}")

        return _emit(args, payload, render)

    def run(engine) -> int:
        result = engine.verify(pack_id=args.pack or "", subject_id=args.subject or "",
                               limit=args.limit)
        return _emit(
            args, result,
            lambda: print(f"job {result.get('job_id', '')} started: re-reading the sources "
                          "behind every claim on this screen"),
        )

    return _with_engine(args, run)


def cmd_drafts(args, store) -> int:
    from app import clidirect

    if args.action == "list" or not args.action:
        payload = clidirect.drafts(args.store)

        def render() -> None:
            items = payload.get("items", [])
            if not items:
                print("no pack drafts — an agent has not written one yet")
                return
            for item in items:
                print(f"  {item.get('slug', ''):24} "
                      f"{'built' if item.get('built') else 'unbuilt':8} "
                      f"{'installed' if item.get('installed') else ''}")

        return _emit(args, payload, render)

    if args.action == "show":
        if not args.slug:
            print("kriko: this action needs a draft slug", file=sys.stderr)
            return 1
        try:
            payload = clidirect.draft(args.store, args.slug)
        except KeyError as exc:
            print(f"kriko: {exc.args[0]}", file=sys.stderr)
            return 1
        return _emit(args, payload,
                     lambda: print(json.dumps(payload, indent=2, default=str)))

    if not args.slug:
        print("kriko: this action needs a draft slug", file=sys.stderr)
        return 1

    def run(engine) -> int:
        if args.action == "amend":
            result = engine.amend_draft(args.slug, note=args.note or "")
            return _emit(args, result,
                         lambda: print(f"job {result.get('job_id', '')} started: covering what "
                                       f"{args.slug} is missing"))
        if args.action == "build":
            result = engine.build_draft(args.slug)
            return _emit(args, result,
                         lambda: print(f"built {result.get('artifact', '')}"))
        if args.action == "install":
            result = engine.install_draft(args.slug)
            return _emit(args, result,
                         lambda: print(f"installed {result.get('pack_id', '')} from draft {args.slug}"))
        if args.action == "discard":
            engine.discard_draft(args.slug)
            result = {"discarded": args.slug}
            return _emit(args, result, lambda: print(f"discarded draft {args.slug}"))
        print(f"kriko: unknown drafts action {args.action!r}", file=sys.stderr)
        return 1

    return _with_engine(args, run)


def cmd_operations(args, store) -> int:
    from app import clidirect

    conn, _ = _app_conn(args)
    try:
        payload = clidirect.operations(conn, limit=args.limit)
    finally:
        conn.close()

    def render() -> None:
        items = payload.get("items", [])
        if not items:
            print("no operations recorded yet")
            return
        print(f"{payload.get('running', 0)} running now")
        for row in items:
            cost = f"${row['usd']:.2f}" if row.get("usd") else \
                (f"{row['tokens']}tok" if row.get("tokens") else "")
            print(f"  [{row.get('state', ''):8}] {row.get('door', ''):5} "
                  f"{row.get('kind', ''):10} {row.get('name', ''):24} {cost:>8} "
                  f"{row.get('subject_id', '')}")

    return _emit(args, payload, render)


def _version() -> str:
    """The installed version, or a readable admission that it cannot be told.

    Imported here rather than at module scope: `--version` has to work in an
    environment broken enough that the answer is interesting, and an import
    that raises at the top of this file would make the diagnostic itself the
    thing that fails.
    """
    try:
        from app.version import app_version

        return app_version()
    except Exception:  # noqa: BLE001 — a broken install must still answer
        return "unknown (this install cannot report its own version)"


def _peek_command(argv: list[str]) -> str | None:
    """The subcommand being run, parsed with a throwaway parser that imports
    nothing heavy — so `build_parser` can skip importing what it does not need.

    `app.agentbench.cli` costs seconds to import (its runner reaches every
    provider), and it used to be imported while *building* the parser, i.e. on
    every `kriko` invocation including `--version`. The real parser is built
    with the peeked command, and only `agent-bench` gets its own arguments
    wired up.
    """
    peek = argparse.ArgumentParser(prog="kriko", add_help=False)
    peek.add_argument("--store")
    peek.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    peek.add_argument("--version", action="store_true", default=argparse.SUPPRESS)
    peek.add_argument("command", nargs="?")
    peek.add_argument("rest", nargs=argparse.REMAINDER)
    known, _ = peek.parse_known_args(argv)
    return known.command


def build_parser(command: str | None = None) -> argparse.ArgumentParser:
    from kriko.store.db import DEFAULT_STORE

    parser = argparse.ArgumentParser(prog="kriko", description=__doc__.split("\n")[0])
    parser.add_argument("--store", default=None,
                        help=f"store file (default: {DEFAULT_STORE})")
    parser.add_argument("--json", action="store_true",
                        help="print the answer as one JSON document")
    # The cheapest possible "is this install actually working". It needs no
    # store, no packs and no network, so it is the one command a smoke check
    # can run in a clean environment — and `tools/smoke_wheel.sh` does,
    # because the reader's `kriko` failed on an import before any subcommand
    # was reached and nothing in the tree would have noticed.
    parser.add_argument(
        "--version", action="version",
        version=f"kriko {_version()}",
        help="print the installed version and exit")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("packs", help="list installed packs")
    _add_json(p)
    p.set_defaults(fn=cmd_packs)

    p = sub.add_parser("install", help="install a .kpack file")
    p.add_argument("path")
    _add_json(p)
    p.set_defaults(fn=cmd_install)

    p = sub.add_parser("uninstall", help="remove a pack completely")
    p.add_argument("pack_id")
    _add_json(p)
    p.set_defaults(fn=cmd_uninstall)

    p = sub.add_parser("enable", help="enable or disable a pack without removing it")
    p.add_argument("pack_id")
    p.add_argument("--disable", action="store_true")
    _add_json(p)
    p.set_defaults(fn=cmd_enable)

    p = sub.add_parser("build", help="build a pack directory into a .kpack")
    p.add_argument("root")
    p.add_argument("--out")
    p.add_argument("--force", action="store_true",
                   help="write the pack even if it has no subjects and no claims")
    _add_json(p)
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("lookup", help="ask the installed packs about a product")
    p.add_argument("identity", nargs="*", metavar="key=value")
    p.add_argument("--kind", default="product")
    p.add_argument("--ctx", nargs="*", metavar="key=value",
                   help="what this one has been through: usage_km=180000")
    p.add_argument("--lang", default="en")
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("-v", "--verbose", action="store_true",
                   help="show why each claim ranked where it did, and its sources")
    _add_json(p)
    p.set_defaults(fn=cmd_lookup)

    p = sub.add_parser("bench", help="measure the research planes on the same cases")
    p.add_argument("--suite", choices=("precision", "web"), default="precision",
                   help="controlled configuration evidence, or legacy live web research")
    p.add_argument("--plane", action="append", default=[],
                   help="harness | api (repeatable; default: whatever runs here)")
    p.add_argument("--cases", type=int, default=3, help="how many subjects")
    p.add_argument("--pack", default="", help="only subjects from this pack")
    p.add_argument("--documents", type=int, default=3,
                   help="max sources per case")
    p.add_argument("--budget", type=float, default=0.20,
                   help="USD ceiling per case on the paid plane")
    p.add_argument("--protocol", action="append", default=[],
                   help="narrow | standard | wide (repeatable; default: whatever "
                        "the plane would choose from past measurements)")
    p.set_defaults(fn=cmd_bench)

    p = sub.add_parser(
        "agent-bench",
        help="grade agents on fixed tasks, like Terminal-Bench but for this: "
             "resolve rate, consistency, settings obeyed")
    if command == "agent-bench":
        # The only subcommand whose argument wiring imports the bench's runner
        # tree; built only when this is the command being run.
        from app.agentbench.cli import add_arguments as add_agent_bench_arguments

        add_agent_bench_arguments(p)
    else:
        p.add_argument("rest", nargs=argparse.REMAINDER)
    p.set_defaults(fn=cmd_agent_bench, needs_store=False)

    p = sub.add_parser(
        "model-bench",
        help="measure models on a fixed corpus: how many tokens, and how often "
             "they invent something (writes JSON, CSV and a report)")
    p.add_argument("rest", nargs=argparse.REMAINDER,
                   help="one of: list | plan | run — for example "
                        "`kriko model-bench run --candidates local:qwen3.5:4b`")
    p.set_defaults(fn=cmd_model_bench, needs_store=False)

    # ── the research door for agents: JSON in, JSON out, same acceptance
    # path as the MCP tools of the same names (`app/agentops.py`).

    p = sub.add_parser("agenda", help="what to research next, ranked (JSON)")
    p.add_argument("--pack", default="", help="only this pack")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(fn=cmd_agenda)

    p = sub.add_parser("brief", help="what to research about one subject (JSON)")
    p.add_argument("subject_id")
    p.add_argument("--pack", required=True, help="the pack the subject is in")
    p.add_argument("--effort", choices=("fast", "deep"), default="fast",
                   help="how much run this is: fast (minutes) or deep "
                        "(a budgeted tree with follow-up rounds)")
    p.set_defaults(fn=cmd_brief)

    p = sub.add_parser("loopscore", help="how well the research loop is running for one "
                          "subject (JSON)")
    p.add_argument("subject_id")
    p.add_argument("--pack", required=True, help="the pack the subject is in")
    p.add_argument("--limit", type=int, default=50,
                   help="how many submissions to read (default 50)")
    p.set_defaults(fn=cmd_loopscore)

    p = sub.add_parser("submit", help="file findings for one subject; ungrounded ones are refused")
    p.add_argument("subject_id")
    p.add_argument("findings",
                   help="JSON file: a list of findings, or {findings, queries}; "
                        "'-' reads stdin. Each finding: title, domain, severity, "
                        "quote, source_url, document_text, rationale")
    p.add_argument("--pack", required=True, help="the pack the subject is in")
    p.add_argument("--query", action="append", default=[],
                   help="a search you ran to find these (repeatable)")
    p.set_defaults(fn=cmd_submit)

    p = sub.add_parser("tui", help="operator console: planes, agenda, jobs, shell")
    p.add_argument("--url", default="",
                   help="engine to attach to (default: a running app, else start one)")
    p.add_argument("--no-start", action="store_true",
                   help="attach only — fail rather than starting an engine")
    # The one command here that talks to an engine over HTTP rather than
    # opening the store: whichever engine it attaches to owns that file, and a
    # second writer on it would be this process fighting the app it just
    # attached to.
    p.set_defaults(fn=cmd_tui, needs_store=False)

    # ── the app-state commands. The read half (prefs read, costs, sites list,
    # verify --list, drafts list/show, operations) reads `app.sqlite` beside
    # `--store` directly in this process (`app.clidirect`) — no engine is
    # started, and the answer does not depend on one running. The write half
    # (prefs set, sites register/forget, verify, draft actions) enqueues jobs
    # and still goes to an engine over HTTP, for the same second-writer
    # reason `tui` documents.

    def _engine_args(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument(
            "--url", default="",
            help="engine to attach to (default: a running app, else start one)")
        subparser.add_argument(
            "--no-start", action="store_true",
            help="attach only — fail rather than starting an engine")

    p = sub.add_parser("prefs", help="show or change which agent/model/search "
                        "provider is used")
    p.add_argument("--harness", default="", help="preferred coding-agent harness")
    p.add_argument("--model", default="", help="preferred LLM model")
    p.add_argument("--search", default="", help="preferred search provider")
    _engine_args(p)
    _add_json(p)
    p.set_defaults(fn=cmd_prefs, needs_store=False)

    p = sub.add_parser("costs", help="what has been spent, and what the next run "
                        "would likely cost")
    _engine_args(p)
    _add_json(p)
    p.set_defaults(fn=cmd_costs, needs_store=False)

    p = sub.add_parser("sites", help="which sites can be read, and teach it a new one")
    p.add_argument("action", nargs="?", default="list",
                   choices=("list", "register", "forget"))
    p.add_argument("host", nargs="?", default="", help="required for register/forget")
    p.add_argument("--url-for-site", default="",
                   help="a real page on that site, for register")
    p.add_argument("--pack", default="", help="which pack's identity keys to map into")
    _engine_args(p)
    _add_json(p)
    # `sites list` reads the store itself (which adapters are registered live
    # in the store), so this command opens it like `packs` and `lookup` do.
    p.set_defaults(fn=cmd_sites)

    p = sub.add_parser("verify", help="re-read the sources behind installed claims")
    p.add_argument("--list", action="store_true",
                   help="show past checks instead of starting a new one")
    p.add_argument("--verdict", default="", help="filter --list by verdict")
    p.add_argument("--pack", default="", help="only this pack")
    p.add_argument("--subject", default="", help="only this subject")
    p.add_argument("--limit", type=int, default=50)
    _engine_args(p)
    _add_json(p)
    p.set_defaults(fn=cmd_verify, needs_store=False)

    p = sub.add_parser("drafts", help="pack drafts an agent wrote: list, "
                        "amend, build, install, discard")
    p.add_argument("action", nargs="?", default="list",
                   choices=("list", "show", "amend", "build", "install", "discard"))
    p.add_argument("slug", nargs="?", default="")
    p.add_argument("--note", default="", help="what a draft is missing, for amend")
    _engine_args(p)
    _add_json(p)
    p.set_defaults(fn=cmd_drafts, needs_store=False)

    p = sub.add_parser("operations", help="the live feed of agent-driven work, "
                        "whichever door it came through")
    p.add_argument("--limit", type=int, default=50)
    _engine_args(p)
    _add_json(p)
    p.set_defaults(fn=cmd_operations, needs_store=False)

    return parser


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    args = build_parser(_peek_command(argv)).parse_args(argv)
    if getattr(args, "needs_store", True):
        from kriko.store.db import connect

        store = connect(args.store)
    else:
        store = None
    try:
        return args.fn(args, store)
    except (KeyError, ValueError, OSError, RuntimeError, sqlite3.Error) as exc:
        # The CLI is the door an agent uses, and a traceback is not an answer.
        # Each type here is a real, expected failure rather than a bug: a pack
        # id that names nothing (KeyError), a malformed argument (ValueError),
        # a missing file or a full disk (OSError), a store the engine refuses
        # (RuntimeError, e.g. `DowngradeRefused`), and a locked or corrupt
        # database (sqlite3.Error). Anything else keeps its traceback, because
        # hiding an unexpected failure is how a bug becomes a mystery.
        print(f"kriko: {exc}", file=sys.stderr)
        return 1
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
