"""The shell's source parses as Rust, which no other test here checked.

`tauri/` is guarded by four pytest files that read `main.rs` as *text*:
the tray has a Quit, Quit kills the engine, the handshake string matches the
Python side, no engine vocabulary in Rust. Every one of them asserts that some
string is present — and a string is present in code that does not compile.

On 2026-09-10 it wasn't. `main.rs` held three adjacent string literals with no
`concat!` and no commas:

    .message(
        "Kriko is still running so the browser extension can reach it. "
        "Use the Kriko icon near the clock to open it again, or "
        "Quit Kriko to stop it.",
    )

Rust does not join adjacent literals the way C does, so that is a parse error.
It shipped in `a062b86` (B83), survived the `release: 0.5.2` commit, and was
found by the first `cargo` that ever read it — nine minutes into a hand build,
after PyInstaller had already frozen a sidecar.

**The reason it survived is a sentence in a docstring.**
`test_the_shell_runs_in_the_tray.py` said "there is no Rust toolchain on any
machine that touches this tree", and that was taken as settled rather than
re-checked. It was false: this box has `rustc`, and the Windows host it
reaches has the whole toolchain. Twelve careful tests were written *around* an
assumption instead of testing it.

**Why `rustc` and not `cargo check`.** A full check wants the crate's
dependencies and, on Linux, `webkit2gtk`, which is not installed here — so it
would fail on system libraries and say nothing about the code. Parsing needs
neither. `rustc` reports syntax errors *before* it resolves an `extern crate`,
so compiling the file alone reports exactly the class of defect that shipped
and a pile of unresolved-import noise we can discard by construction:

* a parse error is an `error:` with **no** error code,
* an unresolved name is an `error[E0432]` / `error[E0433]`.

That discrimination is the whole gate. It cannot see a type error, and it does
not pretend to — `desktop.yml`'s Windows leg and `packaging/build_desktop.ps1`
are still the only things that compile the crate for real. This catches the
cheaper half for free, on every run, on a machine that has no business
building a Windows bundle.

Skips rather than passes where no `rustc` exists, because a gate that reports
success when it did not run is worse than no gate — that is the failure this
file is about.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

TAURI = Path(__file__).resolve().parents[3] / "tauri"

#: rustc's own way of saying "this has an error code": `error[E0433]: ...`.
#: Anything else on an `error:` line got there without one, which for a single
#: file compiled with no dependencies means the parser refused it.
_CODED = re.compile(r"^error\[E\d+\]")
_SUMMARY = re.compile(r"^error: aborting due to")


def _rustc() -> str | None:
    """A `rustc` to parse with, PATH or not.

    The cargo bin directory is checked explicitly because this repo's own
    shells do not always have it on PATH — and "not on PATH" is what the
    absent toolchain looked like for a month.
    """
    found = shutil.which("rustc")
    if found:
        return found
    home = Path(os.environ.get("CARGO_HOME") or Path.home() / ".cargo")
    candidate = home / "bin" / "rustc"
    return str(candidate) if candidate.exists() else None


def _edition() -> str:
    """The edition the crate declares, not one written down here.

    A gate that parsed as 2021 while the crate moved to 2024 would start
    passing on syntax the real build rejects.
    """
    manifest = (TAURI / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
    found = re.search(r'^edition\s*=\s*"([^"]+)"', manifest, re.MULTILINE)
    return found.group(1) if found else "2021"


def _sources() -> list[Path]:
    return sorted(
        p for p in (TAURI / "src-tauri" / "src").rglob("*.rs")
        if "target" not in p.parts
    )


def test_every_rust_source_parses():
    rustc = _rustc()
    if rustc is None:
        pytest.skip("no rustc on this machine — the Windows leg is the gate there")

    edition = _edition()
    offenders = []
    checked = 0
    for source in _sources():
        checked += 1
        done = subprocess.run(
            [rustc, "--edition", edition, "--crate-type", "lib",
             "--emit=metadata", "-o", os.devnull, str(source)],
            capture_output=True, text=True, cwd=TAURI,
        )
        for line in done.stderr.splitlines():
            if not line.startswith("error"):
                continue
            if _CODED.match(line) or _SUMMARY.match(line):
                continue    # a name this file cannot see, not a syntax error
            offenders.append(f"{source.relative_to(TAURI)}: {line}")

    assert checked >= 1, f"only {checked} Rust source(s) found — is {TAURI} right?"
    assert not offenders, (
        "the shell's source does not parse as Rust, so the Windows build "
        "cannot succeed no matter what the other tauri/ tests say about its "
        "contents:\n  " + "\n  ".join(offenders)
    )
