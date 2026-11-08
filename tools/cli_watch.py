"""Has a coding-agent CLI changed under Kriko, and does Kriko still fit it?

    .venv/Scripts/python.exe tools/cli_watch.py            # check, ask the registries
    .venv/Scripts/python.exe tools/cli_watch.py --offline  # check, no network
    .venv/Scripts/python.exe tools/cli_watch.py --accept   # record what passed as last known good
    .venv/Scripts/python.exe tools/cli_watch.py --json     # the rows, for a script

For every CLI in `harness.KNOWN` that is installed here it reads the version,
checks the flags and values Kriko passes against the CLI's own `--help`
(`app.cliwatch.contract_for`), and compares both with the last known good in
`src/app/cli_versions.json`. Unless `--offline`, it also asks npm / PyPI for
the newest published version, so an upgrade is seen before it is installed.

Exit status:

* 0 — every installed CLI matches its last known good and its contract holds;
* 1 — a CLI's version or declared flags changed since last known good, or a
  contract is degraded: re-verify, then `--accept`;
* 2 — a contract is broken: Kriko cannot start that CLI as it stands;
* with `--fail-on-upstream`, 1 also when a newer version is published than the
  one recorded as good (the early warning, before anyone upgrades).

`--accept` records only CLIs whose contract is not broken, so a broken CLI
stays red until the harness row is adapted to it.

A daily Windows scheduled task (the log keeps the diffs):

    schtasks /create /sc daily /st 09:00 /tn KrikoCliWatch /tr ^
      "cmd /c cd /d C:\\path\\to\\kriko && .venv\\Scripts\\python.exe tools\\cli_watch.py --fail-on-upstream >> %LOCALAPPDATA%\\kriko-cli-watch.log 2>&1"
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from app import cliwatch  # noqa: E402


def _newer(published: str, recorded: str) -> bool:
    def key(text: str) -> tuple:
        parts = []
        for piece in text.split("-")[0].split("+")[0].split("."):
            parts.append(int(piece) if piece.isdigit() else -1)
        return tuple(parts)

    return bool(published and recorded) and key(published) > key(recorded)


def render(rows: list[dict], *, upstream: bool) -> list[str]:
    lines = []
    for row in rows:
        if not row["installed"]:
            lines.append(f"  -  {row['label']:<18} not installed")
            continue
        state = row["state"]
        mark = {"ok": "ok ", "degraded": "!! ", "broken": "XX ", "unknown": "?? "}[state]
        if state == "ok" and row["changed"]:
            mark = "!! "
        version = row["version"] or "?"
        known = row["known_good"] or "unrecorded"
        head = f"  {mark}{row['label']:<18} {version:<12} last known good {known}"
        if upstream and row.get("latest"):
            head += f"   published {row['latest']} ({row.get('registry')})"
        lines.append(head)
        if row["version"] and row["version"] != row["known_good"]:
            lines.append(f"       ~ version: {known} -> {row['version']}")
        for flag in row["missing_must"]:
            lines.append(f"       - required flag gone: {flag}")
        for flag in row["missing_should"]:
            lines.append(f"       - optional flag gone: {flag}")
        for value in row["missing_values"]:
            lines.append(f"       - help no longer names: {value}")
        for flag in row["lost"]:
            lines.append(f"       - declared at last known good, not now: {flag}")
        if state == "unknown":
            lines.append("       ? the CLI printed no help; its contract could not be read")
        if upstream and _newer(row.get("latest", ""), row["known_good"] or row["version"]):
            lines.append(f"       + newer release published: {row['latest']}")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true", help="do not ask npm / PyPI")
    parser.add_argument("--accept", action="store_true",
                        help="record every installed, non-broken CLI as last known good")
    parser.add_argument("--json", action="store_true", help="print the rows as JSON")
    parser.add_argument("--fail-on-upstream", action="store_true",
                        help="exit 1 when a newer version is published than the one recorded")
    parser.add_argument("--baseline", type=Path, default=cliwatch.BASELINE)
    args = parser.parse_args(argv)

    baseline = cliwatch.load_baseline(args.baseline)
    report = cliwatch.check_all(latest=not args.offline, baseline=baseline)

    # With `--json` stdout is the rows and nothing else; the verdict goes to stderr.
    def say(text: str) -> None:
        print(text, file=sys.stderr if args.json else sys.stdout)

    if args.json:
        print(json.dumps(report.rows, indent=2))
    else:
        print("agent CLIs against their last known good:")
        print("\n".join(render(report.rows, upstream=not args.offline)))

    if args.accept:
        today = datetime.date.today().isoformat()
        updated = cliwatch.accepted(report.rows, baseline, today=today)
        cliwatch.save_baseline(updated, args.baseline)
        moved = sorted(k for k in updated if updated[k] != baseline.get(k))
        say(f"\nrecorded as last known good in {args.baseline}: "
              + (", ".join(moved) or "nothing new"))
        return 2 if report.broken else 0

    if report.broken:
        say("\nBROKEN: " + "; ".join(cliwatch.summary(r) for r in report.broken))
        return 2
    upstream = [r for r in report.rows
                if _newer(r.get("latest", ""), r["known_good"] or r["version"])]
    if report.changed:
        say("\nCHANGED since last known good - check the runs, adapt the harness row "
              "if needed, then `tools/cli_watch.py --accept`.")
        return 1
    if args.fail_on_upstream and upstream:
        say("\nUPSTREAM: newer releases published for "
              + ", ".join(r["label"] for r in upstream))
        return 1
    say("\nall installed CLIs match their last known good.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
