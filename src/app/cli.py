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
"""

import argparse
import sys
from pathlib import Path

from kriko.lookup import lookup
from kriko.lookup.query import Query
from kriko.store import packstore
from kriko.store.db import DEFAULT_STORE, connect


def _kv(pairs: list[str]) -> dict:
    """Parse `key=value` arguments, keeping numbers numeric."""
    out = {}
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


def cmd_packs(args, store) -> int:
    rows = packstore.installed_packs(store)
    if not rows:
        print("no packs installed — try: kriko install <file.kpack>")
        return 0
    print(f"{'PACK':<28} {'VERSION':<10} {'STATE':<9} {'TRUST':>6}  NAME")
    for row in rows:
        state = "enabled" if row["enabled"] else "disabled"
        print(f"{row['pack_id']:<28} {row['version']:<10} {state:<9} "
              f"{row['trust_weight']:>6.2f}  {row['name']}")
    return 0


def cmd_install(args, store) -> int:
    pack_id = packstore.install(store, args.path)
    counts = {
        table: store.execute(
            f"SELECT COUNT(*) FROM {table} WHERE pack_id = ?", (pack_id,)).fetchone()[0]
        for table in ("subjects", "claims", "evidence")
    }
    print(f"installed {pack_id}: "
          + ", ".join(f"{v} {k}" for k, v in counts.items()))
    return 0


def cmd_uninstall(args, store) -> int:
    packstore.uninstall(store, args.pack_id)
    print(f"uninstalled {args.pack_id} — every other pack is untouched")
    return 0


def cmd_enable(args, store) -> int:
    packstore.set_enabled(store, args.pack_id, not args.disable)
    print(f"{args.pack_id}: {'disabled' if args.disable else 'enabled'}")
    return 0


def cmd_build(args, store) -> int:
    # Imported here: the builder pulls in yaml and tomllib, which a reader who
    # only ever installs packs should not pay for on every command.
    import importlib

    from kriko.pack.build import build as generic_build, digest_of
    from kriko.store.db import connect as connect_store

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

    conn = connect_store(out)
    try:
        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("subjects", "claims", "evidence")
        }
    finally:
        conn.close()

    print(f"built {out}  digest {digest_of(out)[:16]}")
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

    return 0


def cmd_lookup(args, store) -> int:
    result = lookup(store, Query(
        kind=args.kind,
        identity=_kv(args.identity),
        context=_kv(args.ctx or []),
        lang=args.lang,
        limit=args.limit,
    ))

    res = result.resolution
    print(f"match: {res.method}  ({len(res.subject_ids)} subject(s))  "
          f"coverage: {result.coverage}")
    if res.notes:
        print(f"  {res.notes}")
    for flag in res.flags:
        print(f"  flag: {flag}")

    if not result.claims:
        print("\nno claims for this one.")
        return 0

    print()
    for n, claim in enumerate(result.claims, 1):
        mark = " [disputed]" if claim.disputed else ""
        print(f"{n}. [{claim.severity}] {claim.title}{mark}")
        print(f"   {claim.subject_label}  ·  {claim.domain}  ·  "
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
    return 0


def cmd_tui(args, store) -> int:
    """The operator console. Imported here, not at module scope.

    `kriko lookup` must not pay for a terminal UI it will never draw, and
    `app.tui` reaches `app.web` (to start an engine when none is running),
    which is a whole FastAPI app's import cost on a command that answers a
    question about a car in milliseconds.
    """
    from app.tui import main as run_tui

    return run_tui(url=args.url, allow_start=not args.no_start)


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
            analysis_log_path=store_path.parent / "analyses.jsonl",
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
                    f"  — all the same way, which is a mis-use rather than bad luck"
                    if line["dominant_failure"]
                    else ""
                )
            )
        print()
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kriko", description=__doc__.split("\n")[0])
    parser.add_argument("--store", default=None,
                        help=f"store file (default: {DEFAULT_STORE})")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("packs", help="list installed packs").set_defaults(fn=cmd_packs)

    p = sub.add_parser("install", help="install a .kpack file")
    p.add_argument("path")
    p.set_defaults(fn=cmd_install)

    p = sub.add_parser("uninstall", help="remove a pack completely")
    p.add_argument("pack_id")
    p.set_defaults(fn=cmd_uninstall)

    p = sub.add_parser("enable", help="enable or disable a pack without removing it")
    p.add_argument("pack_id")
    p.add_argument("--disable", action="store_true")
    p.set_defaults(fn=cmd_enable)

    p = sub.add_parser("build", help="build a pack directory into a .kpack")
    p.add_argument("root")
    p.add_argument("--out")
    p.add_argument("--force", action="store_true",
                   help="write the pack even if it has no subjects and no claims")
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
    p.set_defaults(fn=cmd_lookup)

    p = sub.add_parser("bench", help="measure the research planes on the same cases")
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

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    store = connect(args.store) if getattr(args, "needs_store", True) else None
    try:
        return args.fn(args, store)
    except (KeyError, ValueError, FileNotFoundError) as exc:
        print(f"kriko: {exc}", file=sys.stderr)
        return 1
    finally:
        if store is not None:
            store.close()


if __name__ == "__main__":
    raise SystemExit(main())
