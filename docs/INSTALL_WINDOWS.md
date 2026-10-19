# Install Kriko on Windows

This guide installs the app, prepares the browser extension, and reports a
problem.

| You have | Go to |
|---|---|
| `kriko-<version>-x86_64.msi` | Path A, steps 1 to 3 |
| `kriko-<version>-win64-portable.zip` | Path A, step 1 (the portable ZIP), then step 2 |
| Python 3.13 or newer, and no installer | Path B, steps 4 to 6 |

Path A needs nothing more. The app contains its own Python. A catalog lookup
needs no network.

## Path A: the desktop app

### 1. Install the app

Double-click `kriko-<version>-x86_64.msi`.

The install puts the app in `%LOCALAPPDATA%\Programs\Kriko`. It does not ask
for administrator rights. Two programs go there.

| Program | Function |
|---|---|
| `kriko.exe` | The app. It starts the engine and stops the engine. |
| `kriko-sidecar.exe` | The engine. The app starts it, and the app stops it. |

The last screen of the install has the checkbox **Open Kriko**. Keep the
checkbox on and press **Finish**. The app opens. A silent install
(`msiexec /qn`) opens nothing.

A newer MSI replaces an older one and stops a running Kriko first. An older MSI
refuses to install over a newer one.

> **The message "A newer version of Kriko is already installed."**
> You started an older MSI. Keep the newer version, or uninstall the newer
> version first (step 3).

**The portable ZIP.** Extract `kriko-<version>-win64-portable.zip`. Keep
`kriko.exe` and `kriko-sidecar.exe` in the same folder. Run `kriko.exe`.

### 2. Open the app

Open **Kriko**. The window shows the start, then the app.

The first start shows a setup with four steps. The setup selects an agent,
installs a catalog, and prepares the browser extension. To show the setup
again, open **Settings** and press **Take the tour**.

Kriko keeps your data in `%USERPROFILE%\.kriko`.

If you close the window, the app hides. The engine continues, because the
browser extension needs it. To stop Kriko, use the tray icon and select
**Quit**.

> **The window shows a failure screen.**
> The screen shows the error from the engine. A usual cause is a program that
> holds port 8787. Stop that program and open Kriko again.

> **An update fails.**
> Kriko still runs. Most updates replace only the engine: Kriko unpacks it into
> `%LOCALAPPDATA%\Kriko\engines`, restarts the engine and keeps the window open.
> If the new engine cannot start, Kriko sets it aside and starts the engine that
> came with the app. When a release changes the app itself, Update now runs the
> installer instead. If that fails, select **Quit** in the tray menu and start the
> installer again. You never need to uninstall first.

Examine the engine from a browser. Open `http://127.0.0.1:8787/api/health`. The
answer contains `{"ok":true,...}`.

### 3. Remove the app

Open **Settings**, then **Apps**, then **Installed apps**. Select **Kriko** and
press **Uninstall**.

The uninstall keeps `%USERPROFILE%\.kriko`. To remove your catalogs and your
history, delete that folder.

## Prepare the browser extension

Kriko does not come from a browser store. Load the extension from a folder.

1. Open **Browser extension** in Kriko and press **Stage**. If Kriko prepared
   the files before, the key says **Refresh**.
2. Press **Show folder**. Kriko opens `%USERPROFILE%\.kriko\extension\`.
3. Open the extensions page of your browser.
4. Turn on **Developer mode**.
5. Press **Load unpacked** and select the folder that holds `manifest.json`.
6. Pin Kriko in the toolbar.

| Browser | Extensions page |
|---|---|
| Chrome | `chrome://extensions` |
| Edge | `edge://extensions` |
| Brave | `brave://extensions` |

Kriko must run before you open a listing. The extension asks the engine for
every answer.

> **After an update of the app**, the extension can be older than the app. Press
> **Refresh** on the **Browser extension** screen. Then press the reload key on
> the card of the extension in the browser.

### Give the extension the sites

A site in Kriko is not sufficient. Only the browser gives a site permission.

1. Right-click the extension button and select **Options**.
2. Press **Allow the pending sites** and agree.
3. Open the page again.

> **The panel is missing on a page.**
> Open **Sites**. The screen says if the site needs a permission, or if no
> adapter reads the site.

### Firefox

Kriko also has a Firefox add-on.

1. Open **Browser extension** and press **Prepare Firefox**.
2. Open `about:debugging#/runtime/this-firefox`.
3. Press **Load Temporary Add-on** and select the `manifest.json` file that the
   screen shows.

Firefox removes a temporary add-on at the next start. A permanent installation
needs an add-on file that Mozilla signed.

## Path B: from Python

Use Path B for a terminal and a browser tab. Python 3.13 or newer is required.

### 4. Examine your Python

```powershell
py -3.13 --version
```

> **The message "py is not recognised".**
> Install Python from [python.org/downloads](https://www.python.org/downloads/),
> and select **Add python.exe to PATH**.

### 5. Install Kriko in its own folder

```powershell
py -3.13 -m venv $HOME\kriko-env
$HOME\kriko-env\Scripts\pip install --upgrade pip
$HOME\kriko-env\Scripts\pip install kriko
```

From a source checkout, use the folder in the last command:
`$HOME\kriko-env\Scripts\pip install C:\path\to\kriko`.

Examine the installation:

```powershell
$HOME\kriko-env\Scripts\kriko --version
```

A version number shows a good installation. No data, no catalog, and no
network are necessary.

> **The message "ModuleNotFoundError: No module named 'kriko'".**
> ```powershell
> $HOME\kriko-env\Scripts\pip show -f kriko
> $HOME\kriko-env\Scripts\python -c "import kriko, app; print('both import')"
> where.exe kriko
> ```
> * The command `pip show -f` lists no `kriko\` file. The installation file is
>   bad. Report the problem.
> * Both imports work, but `kriko` fails. An older installation is before this
>   one in `PATH`.
> * The command `pip show` finds nothing. You used the wrong interpreter. Do
>   step 5 again with full paths.

### 6. Start the engine

```powershell
$HOME\kriko-env\Scripts\python -m app.web
```

Keep that window open. Then prepare the browser extension as above.

| Address | Contents |
|---|---|
| `http://127.0.0.1:8787/api/docs` | The interactive API |
| `http://127.0.0.1:8787/api/health` | The status |

For a terminal interface, use `$HOME\kriko-env\Scripts\kriko tui`.

Remove the installation:

```powershell
Remove-Item -Recurse $HOME\kriko-env
```

`%USERPROFILE%\.kriko` stays, as in step 3.

## Report a problem

Give these data:

```powershell
$HOME\kriko-env\Scripts\kriko --version
$HOME\kriko-env\Scripts\pip show -f kriko
```

Also give `http://127.0.0.1:8787/api/health` if the app started. On Path A, say
if you used the MSI or the portable ZIP.
