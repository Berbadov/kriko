# The Kriko desktop app

This folder holds the desktop app. It uses Tauri: a Rust shell and a React
window. The shell supervises the engine. The window draws every screen from the
local HTTP API. Neither holds engine logic. The browser extension is a separate
part of the tree, in `extension/`.

Three screens carry the app:

- **Chat** is the welcome page. You ask, and the engine researches.
- **Compare** puts products in columns and risks in rows. An agent dock answers
  questions about the shortlist, and the research queue feeds it.
- **Product** is the page the browser extension opens after a quick check. It
  holds the saved check and a follow-up chat about that product.

## Run it from a source checkout

You need Node.js, a Rust toolchain, and the Python environment of the engine
(`tools/setup.sh`).

```
cd kriko-ui
npm ci
npm run tauri dev
```

The window hot-reloads. The shell starts the engine with `python -m app.sidecar`
from the checkout. To work on the interface without the shell, run `npm run dev`
and open `http://localhost:5173`. The Vite server proxies `/api` to the engine,
and the app shows demo data when no engine answers.

## The files

| File | Function |
|---|---|
| `src/App.tsx`, `src/ui/` | The shell of the window: the rail, the drawer, and the shared pieces (composer, markdown, product card, queue card). |
| `src/screens/` | One file for each screen: Chat, Compare, Product, Queue, and the rest. |
| `src/engine/` | The engine from the side of the window: the API client, the boot state, and the typed products and jobs. |
| `src/chat.tsx`, `src/compare.tsx`, `src/queue.tsx` | The state of the three pillars. Each lives above the screens, so a run survives a change of screen. |
| `src/handoff.ts` | The route that the extension hands over: `check`, `result/<id>`, `questions/<id>`, `compare/<id>`, `queue`. |
| `src/styles/tokens.css` | Every colour, size and time. The dark palette is the default and the light palette redefines each colour. |
| `src-tauri/src/engine.rs` | The engine supervisor. |
| `src-tauri/src/shell.rs` | The tray, the hide-on-close behaviour, and the window. |
| `src-tauri/src/lib.rs` | The commands the window calls, and the start of the app. |

## The engine supervisor

The app is a supervisor. It is not a second engine. `engine.rs` finds the
engine, waits until the engine answers, and stops the engine with the app. The
engine comes from the first of these that is available:

1. `KRIKO_URL`, if you set it. The app attaches and starts nothing.
2. `kriko-sidecar` beside `kriko.exe`, with its `_internal` folder next to it. The app starts it.
3. An engine that already answers on port 8787. The app attaches to it.
4. `python -m app.sidecar` from a checkout (`.venv`).

| Moment | Result |
|---|---|
| Handshake | The first line with `KRIKO_PORT` names a port that the engine already holds. |
| Crash belt | `--exit-with-parent` makes the engine watch its input. If the app stops in any way, the engine stops too. |
| Failure | The engine did not start, did not answer, or stopped. The window shows the last lines of its error output, and **Try again** starts it once more. |
| Close the window | The window hides. The engine continues, because the browser extension needs it. |
| **Quit** in the tray | The app stops the engine, then itself. On Windows the stop is a tree kill, because the frozen engine starts a second process. |
| An attached engine | The app leaves it. It was not the engine of this app. |
| A second start | The first window comes to the front and the second app stops. |

The window never sends an `Origin` header to the engine from inside the app.
`engine_request` in `lib.rs` makes the call from Rust, and the engine accepts
native clients. In a browser, the engine accepts only loopback pages.

## Build the installer

Build the Windows installer and the portable ZIP on Windows:

```
powershell -ExecutionPolicy Bypass -File kriko-ui/package.ps1
```

You need a Rust toolchain (MSVC) and Node.js on `PATH`. The first build
downloads the NSIS tools that Tauri uses. Add `-InstallCheck` to also install
the result into a scratch folder and remove it. That check refuses to run where
a Kriko is already installed.

The script freezes the engine, proves it answers, stages it and OpenSERP in
`src-tauri/binaries` with the target triple in the name, and runs
`tauri build --config src-tauri/tauri.bundle.conf.json -- --locked`. The names
of the two programs are in the bundle config and not in `tauri.conf.json`,
because `tauri dev` has no frozen engine to name. The build writes these files
to `kriko-ui/builds/`:

| File | Contents |
|---|---|
| `kriko-<version>-x86_64-setup.exe` | The per-user installer for Windows. It needs no administrator rights. |
| `kriko-<version>-win64-portable.zip` | `kriko.exe`, `kriko-sidecar.exe` (with `_internal\`) and `OpenSERP.exe`, without an install. |
| `kriko-engine-<version>-win64.zip` | The engine alone, for in-app updates. |
| `SHA256SUMS.txt` | The hashes of all three release files. |

Both programs ship in every Windows package, because the app starts the engine
from its own folder. The installer stops a running Kriko first, because a live
engine holds its own program file (`src-tauri/windows/hooks.nsh`).

The Windows installer is unsigned. Windows can show a SmartScreen warning.

## Build the macOS package

Build the Apple Silicon disk image on an Apple Silicon Mac:

```
kriko-ui/package-macos.sh --arch arm64
```

It needs a Rust toolchain, Node.js and Python 3.13 on the machine, and makes its
own `.venv` when there is none. It writes to `kriko-ui/builds/`:

| File | Contents |
|---|---|
| `kriko-<version>-arm64.dmg` | `Kriko.app` and an `Applications` link. |
| `SHA256SUMS-macos.txt` | The digest of the disk image. |

Tauri and PyInstaller cannot cross-compile, so the recipe refuses a Mac whose
architecture is not the one asked for. The engine ships as one file on macOS, so
there is no `_internal` folder to place: `kriko-sidecar` and `openserp` sit in
`Kriko.app/Contents/MacOS`, where the app looks for them. The bundle is ad-hoc
signed unless `KRIKO_MACOS_SIGN_IDENTITY` names a Developer ID identity, and it
is not notarized, so a downloaded copy needs **right-click → Open** the first
time (`docs/INSTALL_MACOS.md`).

The `macos-arm64` job in `desktop.yml` runs this same script on a macOS runner
and uploads the `.dmg` as a workflow artifact. It publishes no release asset:
the release job's evidence (`tools/release_readiness.py`) records a Windows
platform only.

## The look and the motion

Colours come from `src/styles/tokens.css`, and a test fails if a screen names a
colour that the light theme cannot change. **Reduce motion** in Settings stops
every animation. A window that is not in front stops the rest. The file
`src/app/tests/test_the_ui_theme_and_motion_rules.py` holds both rules.

## The checks

```
cd kriko-ui
npx tsc -b            # types
npm run lint          # oxlint
npm run build         # the production bundle
cd src-tauri
cargo test --locked   # the shell
```

`tools/gate.sh tauri` runs the Rust half. The Python tests read the Rust and
TypeScript sources for the rules that no compiler checks.
