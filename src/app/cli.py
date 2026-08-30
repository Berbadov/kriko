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
    from kriko.pack.build import build, digest_of

    root = Path(args.root)
    out = Path(args.out) if args.out else Path("dist") / f"{root.name}.kpack"
    build(root, out)
    print(f"built {out}  digest {digest_of(out)[:16]}")
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

    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    store = connect(args.store)
    try:
        return args.fn(args, store)
    except (KeyError, ValueError, FileNotFoundError) as exc:
        print(f"kriko: {exc}", file=sys.stderr)
        return 1
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
