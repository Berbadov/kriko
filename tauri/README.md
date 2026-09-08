# The desktop shell

A Tauri 2 window around the same server the browser talks to. The engine is not
rewritten in Rust and will not be: `src-tauri/src/main.rs` is a process
supervisor, ~180 lines, and every one of them is about a failure mode.

```
tauri/
  shell-ui/index.html     boot screen + failure screen (no build step, on purpose)
  src-tauri/src/main.rs   spawns the sidecar, reads its port, waits for health
  src-tauri/tauri.conf.json
  src-tauri/capabilities/default.json   spawn the sidecar; nothing else
```

## How a launch goes

1. The window is created **hidden** and loads `shell-ui/index.html`.
2. The page invokes `start_engine`; Rust spawns the `kriko-sidecar` sidecar.
3. The sidecar binds an OS-chosen port and prints `KRIKO_PORT <n>` — see
   `src/app/sidecar.py`, and `src/app/tests/test_sidecar.py` which pins the
   handshake.
4. Rust polls `http://127.0.0.1:<n>/api/health`, then emits `kriko://ready` and
   shows the window. The page replaces itself with the real UI, served by
   FastAPI exactly as it is in a browser.
5. If the sidecar dies or never gets healthy, Rust emits `kriko://failed` with
   the captured stderr and the window shows it. **A blank window is a bug.**
6. On window close and on app exit, the child is killed. An orphaned uvicorn
   holds `~/.kriko/knowledge.sqlite`'s WAL lock and breaks the *next* launch,
   which is the worst kind of failure: invisible and later.

## Building locally

Needs a Rust toolchain (`rustup`), Node, and Python. Neither the wheel nor the
test suite needs any of it — this directory is optional.

```bash
npm --prefix ui run build                       # the UI the sidecar serves
pip install pyinstaller
pyinstaller packaging/kriko-sidecar.spec        # -> dist/kriko-sidecar
# Tauri wants <name>-<target triple>:
mkdir -p tauri/src-tauri/binaries
cp dist/kriko-sidecar "tauri/src-tauri/binaries/kriko-sidecar-$(rustc -Vv | sed -n 's/host: //p')"
npm --prefix tauri install && npm --prefix tauri run tauri build
```

CI does exactly this on macOS, Windows and Linux
(`.github/workflows/desktop.yml`). Bundles are **unsigned**; signing is a
policy decision, not an engineering one, and is deferred.

`src-tauri/Cargo.lock` is committed and every crate in it resolves from
crates.io. Cargo folds all targets into that one file, so the lock a Linux
machine generates pins the Windows and macOS graphs too — which is why
regenerating it needs no Windows box, only `cargo generate-lockfile` in
`tauri/src-tauri/`. Do that in a commit of its own: a dependency bump should be
something someone can read and revert. CI runs `cargo metadata --locked` before
it builds, because cargo will otherwise rewrite a stale lock mid-build and ship
a graph nobody reviewed — v0.2.4 is what that looks like from the outside
(`src/app/tests/test_shell_is_locked.py` holds the rest of the invariant).

## Nothing outlives the app

Three belts, because one was not enough:

1. **`--exit-with-parent`.** The sidecar watches its own stdin, whose write end
   lives in the shell. The shell going away — cleanly, killed, or crashed — is
   an EOF, and the engine stops itself. This is the only one that covers a
   crash, where no handler in `main.rs` runs at all.
2. **`kill_engine`** on window close *and* on `RunEvent::Exit`, since a quit
   from the dock destroys no window.
3. **A tree kill on Windows.** The sidecar is a PyInstaller *onefile* binary:
   the process we spawned is a bootloader that re-execs, and the child is what
   holds the extracted image. `child.kill()` alone leaves it running, so
   `kill_tree` runs `taskkill /F /T /PID`.

The failure this prevents is not a leak, it is the *installer*:

```
Error opening file for writing:
C:\Users\<you>\AppData\Local\Kriko\kriko-sidecar.exe
```

A live sidecar keeps its own `.exe` mapped, so NSIS cannot overwrite it and
offers Abort/Retry/Ignore — and Ignore leaves the old engine beside a new shell.
`src-tauri/installer.nsh` therefore kills the engine in `NSIS_HOOK_PREINSTALL`
too, which is the belt for a machine where one leaked *before* this version.

If you hit that dialog on an older build: close Kriko, run
`taskkill /F /T /IM kriko-sidecar.exe` in a terminal, then run the installer
again.

## Two ports, one server

The window gets an OS-chosen port it is told about. The Chrome extension gets
the fixed `EXTENSION_PORT` (8787) from `app/web/settings.py`, because a page
cannot be told a random number — it has no filesystem and no channel from the
shell. `uvicorn.Server.run` takes a list of sockets, so both are the same
server. If 8787 is taken (a second Kriko, a `python -m app.web` in a terminal)
that door is skipped with a line on stderr and the app opens regardless.

## One store, two front doors

The sidecar resolves `~/.kriko/` the same way the CLI does, so a pack installed
in the app is visible to `python -m app.cli` and the other way round. An
app-private store would silently split a reader's knowledge base in half.

## Self-update

The shell checks for a newer release on startup (`offer_update` in `main.rs`),
asks, and only then downloads, kills the engine and restarts. Killing first is
not optional: the running sidecar holds `knowledge.sqlite`'s WAL lock, and a
restart around it makes the *next* launch fail for a reason nobody can see.

The updater config is not in `tauri.conf.json` — it is applied at build time by
`packaging/configure_updater.py`, from `TAURI_SIGNING_PUBLIC_KEY`. With no key
configured the build produces plain installers and `app.updater()` returns an
error the shell ignores. That is deliberate: committing an endpoint and a
`createUpdaterArtifacts` flag would make every fork's build fail on a missing
secret, and building updater artifacts with a throwaway key would ship an app
that downloads its own updates and then rejects them.

To enable it on this repo:

```bash
npm --prefix tauri run tauri signer generate -w ~/.kriko-updater.key
```

Then set the repository **secret** `TAURI_SIGNING_PRIVATE_KEY` (the file's
contents), the secret `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` if you gave one, and
the repository **variable** `TAURI_SIGNING_PUBLIC_KEY`. The next tag publishes
`latest.json` beside the installers. Keep the private key: rotating it strands
every already-installed copy, which can then only be updated by hand.
