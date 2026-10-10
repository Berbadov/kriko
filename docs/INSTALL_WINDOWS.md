# Installing Kriko on Windows

Double-click the MSI, open Kriko, load the extension. Top to bottom; if a step
fails, **stop** and read the box under it.

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"ui-monospace, SFMono-Regular, Consolas, monospace","primaryColor":"#090E1B","primaryTextColor":"#F2F5FF","primaryBorderColor":"#1F4FFF","lineColor":"#86A3FF","secondaryColor":"#1739C2","tertiaryColor":"#080B16","noteBkgColor":"#BFE4FF","noteTextColor":"#05070F","actorBkg":"#090E1B","actorTextColor":"#F2F5FF","actorBorder":"#1F4FFF","signalColor":"#86A3FF","signalTextColor":"#86A3FF"}}}%%
flowchart LR
    M["Install the MSI<br/>per-user, no admin prompt"]:::brand --> A["Open Kriko<br/>the engine starts with it"]:::plain
    A --> E["Load the unpacked extension"]:::plain --> V["Verify: the panel,<br/>and /api/health"]:::ice
    P["No installer?<br/>pip into a venv"]:::plain -.-> A
    classDef brand  fill:#1F4FFF,stroke:#86A3FF,color:#F2F5FF
    classDef plain  fill:#090E1B,stroke:#3A4156,color:#C9D1EA
    classDef ice    fill:#BFE4FF,stroke:#1F4FFF,color:#05070F
```

| You have | Use |
|---|---|
| `kriko-<version>-x86_64.msi` | Path A, steps 1 to 3 |
| `kriko-<version>-win64-portable.zip` | Path A, step 1 (unzip), then step 2 |
| Neither, but Python | Path B, steps 4 to 6 |

Path A needs nothing else: the app carries its own Python, and a lookup needs
no network.

## Path A: the desktop app

### 1. Install it

Double-click `kriko-<version>-x86_64.msi`. It is a per-user install: no
administrator prompt, nothing under Program Files, and it lands in
`%LOCALAPPDATA%\Programs\Kriko`. Two programs go there, with three shortcuts.

| Shortcut | Opens |
|---|---|
| **Kriko** (Start menu, desktop) | `kriko.exe`, the app. It starts the engine, `kriko-sidecar.exe`, and stops it again |
| **Kriko Console** (Start menu) | The operator console, in a terminal window on purpose |

A newer MSI replaces an older one and stops a running Kriko first. An older MSI
refuses to install over a newer one.

**Portable:** unzip `kriko-<version>-win64-portable.zip` anywhere. It holds
`kriko.exe` and `kriko-sidecar.exe`; keep them side by side and run
`kriko.exe`.

> **"A newer version of Kriko is already installed."** You ran an older MSI.
> Keep the newer one, or uninstall it first (step 3).

### 2. Open it

Start **Kriko**. The window says it is starting, then shows the app. Your data
lives in `$HOME\.kriko`: the store `knowledge.sqlite` and your history
`app.sqlite`.

Closing the window hides it; the engine keeps serving, because the browser
extension needs it. Use the tray icon (**Open**, **Quit**) to end it.

> **The window shows a failure screen instead of the app.** It prints the
> engine's own error. A common cause is another program holding port 8787, the
> one port the extension talks to. Stop that program and open Kriko again.

> **An update fails because Kriko is still running.** Quit it from the tray.
> The installer also stops it; a stray `kriko-sidecar.exe` in Task Manager can
> be ended by hand.

Check the engine from a browser: **http://127.0.0.1:8787/api/health** answers
`{"ok":true,...}`.

### 3. Uninstall

**Settings, Apps, Installed apps, Kriko, Uninstall.** The installer stops
Kriko first. `$HOME\.kriko` (the store and your history) survives. Delete it
too for a full wipe.

## Install the browser extension

Not on a web store: load it from disk.

1. In the app, **Check**, then **Browser extension**, then **Stage** (or
   **Refresh** if already staged). **Show folder** opens `~/.kriko/extension/`.
2. `chrome://extensions`, **Developer mode** on, **Load unpacked**, and pick
   that folder (the one *containing* `manifest.json`). Pin the extension.

> After an app update the card says the staged files are older, and **Refresh**
> followed by the browser's Reload (the circular arrow on the
> extension's card) is the whole repair. The card also compares a content
> digest, so an extension older than this build is caught even when the version
> numbers agree.

### Then grant it the sites

Registering a site in the app is never enough: the browser grants a site
permission only from inside the extension.

1. Right-click the extension's toolbar button, then **Options**, then **Grant**
   each waiting site and confirm. It works from the next page load.
2. The panel is still missing? **System**, then **Sites** says which of the two
   it is: the site needs a permission, or no adapter reads it yet.

## Path B: from Python, without the app

For a terminal and a browser tab. Needs Python 3.13 or newer.

### 4. Check your Python

```powershell
py -3.13 --version
```

Want 3.13 or newer, which is the floor `pyproject.toml` sets and the
interpreter the test suite is verified on.

> **`py` is not recognised.** Install from [python.org/downloads](https://www.python.org/downloads/) with **Add python.exe to PATH** ticked.

### 5. Install into its own place

```powershell
py -3.13 -m venv $HOME\kriko-env
$HOME\kriko-env\Scripts\pip install --upgrade pip
$HOME\kriko-env\Scripts\pip install kriko
```

From a checkout, point the last line at the directory instead:
`$HOME\kriko-env\Scripts\pip install C:\path\to\kriko`.

Check it worked:

```powershell
$HOME\kriko-env\Scripts\kriko --version
```

No data, no catalogs and no network are needed. A version number means a sound
install.

> ### `ModuleNotFoundError: No module named 'kriko'`
> ```powershell
> $HOME\kriko-env\Scripts\pip show -f kriko
> $HOME\kriko-env\Scripts\python -c "import kriko, app; print('both import')"
> where.exe kriko
> ```
> * No `kriko\` files in `pip show -f`: the artifact is bad. Report it.
> * Both import but `kriko.exe` fails: an earlier install is earlier on `PATH`.
> * `pip show` finds nothing: the wrong interpreter. Redo step 5 with full paths.

### 6. Start it

```powershell
$HOME\kriko-env\Scripts\python -m app.web
```

Keep that window open and open **http://127.0.0.1:8787**. For a terminal
interface instead, `$HOME\kriko-env\Scripts\kriko tui`. Then load the
extension as above.

Uninstall:

```powershell
Remove-Item -Recurse $HOME\kriko-env
```

`$HOME\.kriko` survives, as in step 3.

## Reporting a problem

```powershell
$HOME\kriko-env\Scripts\kriko --version
$HOME\kriko-env\Scripts\pip show -f kriko
```

Plus **http://127.0.0.1:8787/api/health**, if the app started. On Path A, say
whether you used the MSI or the zip.
# Local AI setup

Open **Local LLM** in the native app. A local model answers on your own
computer; Ollama is the app that runs its downloaded model files. Research
can still search the web.

Press **Set up Ollama and a starter model** to install Ollama through Windows
App Installer, download the small starter model, and select it in Kriko.
The setup status shows progress and errors. Allow about 6 GB of free space
for the app and starter; larger models need more disk space and memory.

If automatic setup fails, press **Download Ollama manually**. This opens
[Ollama's official Windows download](https://ollama.com/download/windows).
Run its installer, return to Kriko, and press **Check again**. If Ollama is
installed but stopped, **Start Ollama** starts it without downloading a model.
Use **Browse downloadable models** to download another model with progress,
then select it. Model downloads can be cancelled from their progress card.

Small models can miss detailed configurations. The Benchmark screen's
configuration suite measures missed facts, unsupported claims, wrong
specifications, correct abstention, time and token usage on fixed development
cases. It is not a real-world accuracy guarantee.

Windows startup now offers **Off**, **Window** and **Tray** in Settings.
Tray keeps Kriko's engine available in the background; choose Open from its
tray menu to show the window.

Firefox uses a separate package and manifest. Open **Browser Extension**,
press **Prepare Firefox add-on**, and follow the Firefox instructions there.
The release's unsigned XPI is a development package: regular Firefox needs
Mozilla signing for permanent installation. Temporary installation through
`about:debugging` lasts until Firefox restarts. See [Firefox setup](FIREFOX_ADDON.md).
