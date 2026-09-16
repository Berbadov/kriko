# Installing Kriko on Windows

Follow this top to bottom. It assumes nothing and asks you nothing.

If a step fails, **stop there** and read the box under it — each failure below
is one somebody has actually hit.

---

## 1. Check your Python

Open PowerShell and run:

```powershell
py -3.12 --version
```

You want `Python 3.12.x` or newer. Kriko needs 3.13 or newer to run its own
test suite, but 3.12 is enough to install and use it.

> **`py` is not recognised** — Python is not installed. Get it from
> [python.org/downloads](https://www.python.org/downloads/) and tick **Add
> python.exe to PATH** in the installer.

---

## 2. Install into its own place

Do not install into your system Python. A virtual environment keeps Kriko's
dependencies away from everything else, and makes uninstalling it one delete.

```powershell
py -3.12 -m venv $HOME\kriko-env
$HOME\kriko-env\Scripts\pip install --upgrade pip
$HOME\kriko-env\Scripts\pip install kriko
```

Installing from a checkout instead? Use the folder, not the name:

```powershell
$HOME\kriko-env\Scripts\pip install C:\path\to\kriko
```

---

## 3. Check it worked

```powershell
$HOME\kriko-env\Scripts\kriko --version
```

You should see `kriko` and a version number. That command needs no data, no
packs and no network, so if it works, the install is sound.

> ### `ModuleNotFoundError: No module named 'kriko'`
>
> The command was installed and the code behind it was not. This is a
> packaging fault, never something you did. Collect these three answers before
> reporting it — they identify which of the three causes it is:
>
> ```powershell
> $HOME\kriko-env\Scripts\pip show -f kriko
> $HOME\kriko-env\Scripts\python -c "import kriko, app; print('both import')"
> where.exe kriko
> ```
>
> * **`pip show -f` lists no `kriko\` files** — the artifact is wrong.
> * **Both import, but `kriko.exe` fails** — `where.exe kriko` is finding a
>   different install earlier on your PATH. Use the full path above.
> * **`pip show` finds nothing at all** — it installed into another
>   interpreter. Redo step 2, using the full `$HOME\kriko-env\Scripts\` paths
>   rather than a bare `pip`.

---

## 4. Start it

```powershell
$HOME\kriko-env\Scripts\python -m app.web
```

Leave that window open and go to **http://127.0.0.1:8787**.

The terminal console is `$HOME\kriko-env\Scripts\kriko tui` instead, if you
would rather not use a browser.

---

## 5. Install the browser extension

The extension is what puts Kriko on a listing page. It is not on the Chrome
Web Store — you load it from disk.

1. In the app, open **Browser extension** and press **Put the files somewhere
   I can load them**. It tells you the folder. Copy that path.
2. Open `chrome://extensions` in Chrome or Edge.
3. Turn on **Developer mode** (top right).
4. Press **Load unpacked** and pick the folder from step 1.
5. Kriko appears in your extensions list. Pin it so the toolbar button is
   visible.

> **"Manifest file is missing or unreadable"** — you picked the wrong folder.
> Pick the one *containing* `manifest.json`, not its parent.

### Then grant it the sites

This step is separate and it is not optional. Chrome only lets an extension
ask for permission to read a site from inside the extension itself, so
registering a site in the app is never enough on its own.

1. Right-click the Kriko toolbar button → **Options**.
2. Any site waiting on you is listed there. Press **Grant**.
3. Chrome asks you to confirm. The panel works on that site from the next page
   load.

> **The panel does not appear on a site you added** — open the app's **Sites**
> screen. Each site says what is stopping it: *needs permission* means do the
> three steps above; *no adapter* means nothing can read that site yet.

---

## 6. Uninstall

```powershell
Remove-Item -Recurse $HOME\kriko-env
```

Your knowledge and history live in `$HOME\.kriko` and are left alone. Delete
that folder too if you want them gone.

---

## Reporting a problem

Include the output of:

```powershell
$HOME\kriko-env\Scripts\kriko --version
$HOME\kriko-env\Scripts\pip show -f kriko
```

and, if the app started, what **http://127.0.0.1:8787/api/health** returns.
Those three answer most of the questions anybody would ask you.
