"""Noticing that a coding-agent CLI changed, and whether Kriko still fits it.

Kriko drives other vendors' CLIs, and they ship often. `cliprobe` already
adapts to a changed binary: a new stamp drops the cached `--help`, and every
flag decision is made again from the new answer. What it could not do is
*say so*. A CLI that renamed `--output` or stopped listing `stream-json` was
adapted to silently, or refused silently (`command_for` raises `NoHarness`
on a missing required flag), and the first anyone heard of it was a reader's
run that did not start.

This module is the alarm on top of that adaptation, in three parts:

* **The contract** (`contract_for`): what Kriko depends on in one CLI, read
  off its `Harness` row rather than restated — the long options of the launch
  vector and `required` (*must*: the plane cannot start without them), the
  optional flags it attaches when declared (*should*: losing one costs a dial,
  not the plane), and the values it passes to format-like flags, which only
  `--help` can confirm.
* **The version** (`installed_version`): `<cli> --version`, cached in the
  probe store under the binary's stamp, so it is asked once per binary.
* **Last known good** (`cli_versions.json` beside this file): the version and
  the declared dependency flags of each CLI the last time its contract was
  checked and passed. A version that differs from it, or a flag that was
  declared then and is not now, is *drift*: logged once as a warning and served
  on `/api/health` (`cli_drift`) and on each harness row of
  `/api/research-planes` (`cli_watch`). `tools/cli_watch.py` is the same check
  as a command that exits non-zero, and `--accept` moves the baseline.

The latest *published* version (`latest_published`) is a network read, so it
is only ever asked by the tool, never by the engine.

A version is only a trigger here, never a capability: what Kriko does with a
CLI is still decided by its `--help`, as `cliprobe` says. The baseline answers
"has this changed since someone last confirmed it works", which `--help` alone
cannot.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from app.providers import cliprobe, harness

log = logging.getLogger(__name__)

#: The checked-in baseline. Shipped as package data so the engine on a
#: reader's machine compares against the same file the tool writes.
BASELINE = Path(__file__).with_name("cli_versions.json")

#: Where a CLI is published when its install line does not say. Claude Code's
#: Windows install is a script, but the same releases go to npm. A closed,
#: per-CLI vocabulary, like `harness.KNOWN` itself.
REGISTRY_OVERRIDES: dict[str, tuple[str, str]] = {
    "claude-code": ("npm", "@anthropic-ai/claude-code"),
}

_VERSION = re.compile(r"(\d+\.\d+(?:\.\d+)?(?:[-+][0-9A-Za-z.-]+)?)")
_OPTION = re.compile(r"^--[A-Za-z][A-Za-z0-9-]*$")
#: A flag value that `--help` can be expected to list: a plain word such as
#: `stream-json` or `read-only`, not a tool list or a path.
_WORD_VALUE = re.compile(r"^[a-z][a-z-]*$")

_LOCK = threading.Lock()
#: harness id -> the last runtime status, for `/api/health`.
_SNAPSHOT: dict[str, dict] = {}
#: harness ids with a check in flight.
_RUNNING: set[str] = set()
#: (id, version, state) already logged, so a warning is said once.
_WARNED: set[tuple[str, str, str]] = set()


@dataclass(frozen=True)
class Contract:
    """What Kriko depends on in one CLI's `--help`."""

    help_argv: tuple[str, ...]
    must: tuple[str, ...]
    should: tuple[str, ...]
    #: `(flag, value)` pairs whose value the help text should name.
    values: tuple[tuple[str, str], ...] = ()
    #: A word that must appear for the preferred vector (`needs_in_help`);
    #: `fallback` says whether a plain vector exists when it does not.
    needs_word: str = ""
    fallback: bool = False


def _long_options(vector) -> list[str]:
    return [part for part in vector if isinstance(part, str) and _OPTION.match(part)]


def _flag(value: str) -> list[str]:
    return [value] if value and _OPTION.match(value) else []


def contract_for(one: harness.Harness) -> Contract:
    """Derived from the row, so a flag added to a row is watched with no edit here."""
    args = tuple(one.args)
    # `codex exec ...`: the vector's flags belong to the subcommand's help.
    sub = args[0] if args and not args[0].startswith("-") else ""
    help_argv = (sub, "--help") if sub else ("--help",)
    must = _long_options(args) + list(one.required)
    if one.protocol == "codex":
        # Codex's vector is assembled in `command_for`, not in `args`; it is
        # pure for this protocol (no probe), so read the flags off it.
        try:
            must += _long_options(harness.command_for(one))
        except Exception:  # noqa: BLE001 — a contract is still useful without them
            pass
    should = list(one.preferred) + [flag for flag, _ in one.preferred_values]
    if not one.model_unlisted:
        should += _flag(one.model_flag)
    should += _flag(one.effort_flag) + _flag(one.budget_flag) + _flag(one.turns_flag)
    should += _flag(one.reply_flag)
    if one.reader is not None:
        should += _flag(one.reader.config_flag) + _flag(one.reader.grant_flag)
    values = [
        (flag, value) for flag, value in zip(args, args[1:])
        if _OPTION.match(flag) and _WORD_VALUE.match(value)
    ]
    must_set = list(dict.fromkeys(must))
    return Contract(
        help_argv=help_argv,
        must=tuple(must_set),
        should=tuple(f for f in dict.fromkeys(should) if f not in must_set),
        values=tuple(dict.fromkeys(values)),
        needs_word=one.needs_in_help,
        fallback=bool(one.plain_args),
    )


def help_for(executable: str, help_argv: tuple[str, ...]) -> str:
    """The help text the contract is checked against, cached per binary."""
    if help_argv == ("--help",):
        return harness.helptext(executable)
    kind = "help:" + " ".join(help_argv[:-1])
    persisted = cliprobe.entry(executable, kind)
    if persisted is not None:
        return str(persisted[kind])
    text = harness._ask(executable, *help_argv)
    if text:
        cliprobe.record(executable, kind, text)
    return text


def installed_version(executable: str) -> str:
    """`<cli> --version`'s number, `""` when it says none. Cached per binary."""
    persisted = cliprobe.entry(executable, "version")
    if persisted is not None:
        return str(persisted["version"])
    text = harness._ask(executable, "--version", keep_lines=20)
    found = _VERSION.search(text or "")
    version = found.group(1) if found else ""
    if version:
        cliprobe.record(executable, "version", version)
    return version


def check_contract(contract: Contract, text: str) -> dict:
    """`ok`, `degraded` (an optional dial is gone), `broken` (the plane cannot
    start), or `unknown` (the CLI described nothing)."""
    if not text.strip():
        return {"state": "unknown", "missing_must": [], "missing_should": [],
                "missing_values": [], "declared": []}
    found = set(re.findall(r"--[A-Za-z][A-Za-z0-9-]*", text))
    missing_must = [f for f in contract.must if f not in found]
    missing_should = [f for f in contract.should if f not in found]
    missing_values = [f"{flag} {value}" for flag, value in contract.values
                      if value not in text]
    word_missing = bool(contract.needs_word) and contract.needs_word not in text
    if word_missing:
        missing_values.append(contract.needs_word)
    if missing_must or (word_missing and not contract.fallback):
        state = "broken"
    elif missing_should or missing_values:
        state = "degraded"
    else:
        state = "ok"
    declared = sorted(f for f in (*contract.must, *contract.should) if f in found)
    return {"state": state, "missing_must": missing_must,
            "missing_should": missing_should, "missing_values": missing_values,
            "declared": declared}


def load_baseline(path: Path | None = None) -> dict:
    try:
        data = json.loads((path or BASELINE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    clis = data.get("clis") if isinstance(data, dict) else None
    return clis if isinstance(clis, dict) else {}


def save_baseline(clis: dict, path: Path | None = None) -> None:
    body = {"version": 1, "clis": dict(sorted(clis.items()))}
    (path or BASELINE).write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")


def check(one: harness.Harness, baseline: dict | None = None) -> dict:
    """One CLI's status against its contract and its last known good."""
    executable = harness.locate(one)
    row: dict = {"id": one.id, "label": one.label, "path": executable,
                 "installed": bool(executable)}
    known = (load_baseline() if baseline is None else baseline).get(one.id) or {}
    row["known_good"] = known.get("version", "")
    if not executable:
        row.update(version="", state="absent", changed=False, lost=[],
                   missing_must=[], missing_should=[], missing_values=[], declared=[])
        return row
    contract = contract_for(one)
    row["version"] = installed_version(executable)
    row.update(check_contract(contract, help_for(executable, contract.help_argv)))
    was = set(known.get("declared") or ())
    # A flag the CLI declared at last-known-good and does not now: the most
    # specific thing a diff can say, whatever the state.
    row["lost"] = sorted(was - set(row["declared"])) if row["state"] != "unknown" else []
    row["changed"] = bool(
        (row["version"] and row["version"] != row["known_good"]) or row["lost"])
    return row


def needs_attention(row: dict) -> bool:
    return row.get("state") in {"broken", "degraded"} or bool(row.get("changed"))


def summary(row: dict) -> str:
    """One line, for a log and for the screen."""
    parts = []
    if row.get("version") and row.get("version") != row.get("known_good"):
        parts.append(f"version {row.get('known_good') or 'unrecorded'} -> {row['version']}")
    if row.get("missing_must"):
        parts.append("missing required " + ", ".join(row["missing_must"]))
    if row.get("missing_should"):
        parts.append("missing optional " + ", ".join(row["missing_should"]))
    if row.get("missing_values"):
        parts.append("help no longer names " + ", ".join(row["missing_values"]))
    if row.get("lost"):
        parts.append("no longer declares " + ", ".join(row["lost"]))
    state = row.get("state", "")
    head = f"{row.get('label', row.get('id'))}: contract {state}"
    return head + ("; " + "; ".join(parts) if parts else "")


def _remember(row: dict) -> None:
    with _LOCK:
        _SNAPSHOT[row["id"]] = row
        key = (row["id"], str(row.get("version")), str(row.get("state")))
        if not needs_attention(row) or key in _WARNED:
            return
        _WARNED.add(key)
    log.warning("agent CLI drift: %s (tools/cli_watch.py shows the full diff)",
                summary(row))


def _run_check(one: harness.Harness) -> None:
    try:
        _remember(check(one))
    except Exception:  # noqa: BLE001 — a watcher never breaks the thing it watches
        log.debug("cli watch failed for %s", one.id, exc_info=True)
    finally:
        with _LOCK:
            _RUNNING.discard(one.id)


def status(one: harness.Harness) -> dict | None:
    """The last runtime status for `one`, starting a check in the background.

    Never blocks: the first call answers `None` (pending) and the screen asks
    again. A check is re-run when the binary's stamp moved, so an upgrade
    while the app runs is noticed on the next read.
    """
    executable = harness.locate(one)
    stamp = list(cliprobe.stamp(executable)) if executable else []
    with _LOCK:
        row = _SNAPSHOT.get(one.id)
        fresh = row is not None and row.get("_stamp") == stamp
        start = not fresh and one.id not in _RUNNING
        if start:
            _RUNNING.add(one.id)
    if start:
        _spawn(one, stamp)
    if row is None:
        return None
    return public(row)


def _spawn(one: harness.Harness, stamp: list) -> None:
    """Run one check on its own thread; the test suite replaces this."""
    def run() -> None:
        _run_check(one)
        with _LOCK:
            if one.id in _SNAPSHOT:
                _SNAPSHOT[one.id]["_stamp"] = stamp
    threading.Thread(target=run, name=f"kriko-cliwatch-{one.id}", daemon=True).start()


def public(row: dict) -> dict:
    """The additive field a screen reads: small, and nothing it cannot show."""
    return {
        "version": row.get("version", ""),
        "known_good": row.get("known_good", ""),
        "state": row.get("state", ""),
        "changed": bool(row.get("changed")),
        "attention": needs_attention(row),
        "summary": summary(row),
    }


def drift() -> list[dict]:
    """Every checked CLI that needs attention, from the snapshot only.

    `/api/health` is polled by the shell's watchdog, so this never probes.
    """
    with _LOCK:
        rows = list(_SNAPSHOT.values())
    return [{"id": row["id"], **public(row)} for row in rows if needs_attention(row)]


def forget() -> None:
    """Drop the runtime snapshot (tests)."""
    with _LOCK:
        _SNAPSHOT.clear()
        _RUNNING.clear()
        _WARNED.clear()


# ── Where each CLI is published (the tool's network read) ─────────────────────

_NPM = re.compile(r"npm (?:install|i) (?:-g|--global) (@?[\w.-]+(?:/[\w.-]+)?)")
_PYPI = re.compile(r"(?:uv tool install|pipx install|pip install) ([\w.-]+)")


def registry_for(one: harness.Harness) -> tuple[str, str] | None:
    """`("npm" | "pypi", package)`, read off the row's own install line."""
    if one.id in REGISTRY_OVERRIDES:
        return REGISTRY_OVERRIDES[one.id]
    text = f"{one.install_command}\n{one.install_hint}"
    found = _NPM.search(text)
    if found:
        return ("npm", found.group(1))
    found = _PYPI.search(text)
    if found:
        return ("pypi", found.group(1))
    return None


def _get_json(url: str, timeout: float) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json",
                                                   "User-Agent": "kriko-cli-watch"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — fixed https hosts
        return json.loads(response.read().decode("utf-8"))


def latest_published(one: harness.Harness, *, timeout: float = 8.0, fetch=_get_json) -> str:
    """The newest version on the CLI's package registry, `""` when unknown."""
    where = registry_for(one)
    if where is None:
        return ""
    kind, package = where
    try:
        if kind == "npm":
            return str(fetch(f"https://registry.npmjs.org/{package}/latest", timeout).get("version", ""))
        return str(fetch(f"https://pypi.org/pypi/{package}/json", timeout)
                   .get("info", {}).get("version", ""))
    except Exception:  # noqa: BLE001 — no network is an unknown, not a failure
        return ""


@dataclass
class Report:
    rows: list[dict] = field(default_factory=list)

    @property
    def broken(self) -> list[dict]:
        return [r for r in self.rows if r.get("state") == "broken"]

    @property
    def changed(self) -> list[dict]:
        return [r for r in self.rows if needs_attention(r)]


def check_all(*, latest: bool = False, baseline: dict | None = None,
              harnesses: tuple[harness.Harness, ...] | None = None) -> Report:
    base = load_baseline() if baseline is None else baseline
    rows = []
    for one in harnesses if harnesses is not None else harness.KNOWN:
        if one.unusable:
            continue
        row = check(one, base)
        if latest:
            row["latest"] = latest_published(one)
            row["registry"] = "/".join(registry_for(one) or ())
        rows.append(row)
    return Report(rows)


def accepted(rows: list[dict], baseline: dict, *, today: str) -> dict:
    """The baseline with every installed, non-broken CLI recorded as good."""
    out = dict(baseline)
    for row in rows:
        if not row.get("installed") or row.get("state") in {"broken", "unknown"} or not row.get("version"):
            continue
        out[row["id"]] = {"version": row["version"], "declared": row["declared"],
                          "checked": today}
    return out
