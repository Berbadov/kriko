"""The desktop app's source parses as Rust, which no text-reading test checks.

`kriko-gpui/` is guarded by pytest files that read `engine.rs`, `shell.rs` and
`main.rs` as *text*: the tray has a Quit, Quit stops the engine, the handshake
string matches the Python side, no SQL in Rust. Every one of them asserts that
some string is present, and a string is present in code that does not compile.

On 2026-09-10 it wasn't. The previous shell's `main.rs` held three adjacent
string literals with no `concat!` and no commas. Rust does not join adjacent
literals the way C does, so that is a parse error. It shipped, survived a
release commit, and was found by the first `cargo` that ever read it, nine
minutes into a hand build, after PyInstaller had already frozen a sidecar. The
reason it survived was a sentence in a docstring claiming no Rust toolchain
touched the tree, taken as settled rather than re-checked: twelve careful tests
were written *around* an assumption instead of testing it.

**Why `rustc` and not `cargo check`.** A full check wants the crate's
dependencies (GPUI is hundreds of crates) and says nothing when they are not
in the registry cache. Parsing needs none of that. `rustc` reports syntax
errors *before* it resolves a name, so compiling one file alone reports exactly
the class of defect that shipped, plus a pile of unresolved-import noise that
is discarded by construction:

* a parse error is an `error:` with **no** error code,
* an unresolved name is an `error[E0432]` / `error[E0433]`.

Two uncoded messages are also noise by construction: a macro this file cannot
see (`cannot find macro`, from GPUI's `actions!` and friends) and the
"aborting" summary. `tools/gate.sh gpui` runs the real `cargo check` and
`cargo test` where the registry is warm; this is the cheaper half, on every
run, on a machine with no business building a Windows bundle.

Skips rather than passes where no `rustc` exists, because a gate that reports
success when it did not run is worse than no gate.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

CRATE = Path(__file__).resolve().parents[3] / "kriko-gpui"

#: rustc's own way of saying "this has an error code": `error[E0433]: ...`.
#: Anything else on an `error:` line got there without one, which for a single
#: file compiled with no dependencies means the parser refused it.
_CODED = re.compile(r"^error\[E\d+\]")
_SUMMARY = re.compile(r"^error: aborting due to")
#: Names the file cannot see because the crate it belongs to is not linked.
_UNSEEN = re.compile(r"^error: cannot find (attribute|derive|macro)")


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
    manifest = (CRATE / "Cargo.toml").read_text(encoding="utf-8")
    found = re.search(r'^edition\s*=\s*"([^"]+)"', manifest, re.MULTILINE)
    return found.group(1) if found else "2021"


def _sources() -> list[Path]:
    return sorted(
        p for p in (CRATE / "src").rglob("*.rs")
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
            capture_output=True, text=True, cwd=CRATE,
        )
        for line in done.stderr.splitlines():
            if not line.startswith("error"):
                continue
            if _CODED.match(line) or _SUMMARY.match(line) or _UNSEEN.match(line):
                continue    # a name this file cannot see, not a syntax error
            offenders.append(f"{source.relative_to(CRATE)}: {line}")

    assert checked >= 1, f"only {checked} Rust source(s) found — is {CRATE} right?"
    assert not offenders, (
        "the desktop app's source does not parse as Rust, so the Windows "
        "build cannot succeed no matter what the other kriko-gpui tests say "
        "about its contents:\n  " + "\n  ".join(offenders)
    )
