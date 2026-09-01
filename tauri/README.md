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
