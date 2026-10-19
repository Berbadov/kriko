# Install Kriko on Windows

Use the setup EXE or portable ZIP from the latest release. The app contains its
own Python and engine. Published desktop artifacts target Windows x86_64.

## Install the desktop app

Run `kriko-<version>-x86_64-setup.exe`. The NSIS installer installs for your user
without administrator rights. The build is unsigned; Windows may require
**More info → Run anyway**. Keep the installer and its internal files together.

For the portable version, extract the entire `kriko-<version>-win64-portable.zip`
archive before opening `kriko.exe`. Running the executable inside the ZIP is not
an installed portable copy.

Open the app. Its navigation contains **Chat**, **Compare** and **Queue**. Open
**More → Set up Kriko** for the remaining steps.

## Connect an agent

Choose a coding agent, local model, or API agent in **More → Agents**. API keys
are managed in **More → Settings**; local model setup is in **More → Local model**.
Return to setup and press **Check connection**. This sends a short request to
the selected provider. A successful connection test checks answering, not full
source access; complete a sourced product question next.

## Install product knowledge

Open **More → Catalogs → Find release catalogs** and install a catalog. You can
also import a `.kpack` file. The installer ships without a catalog; offline
lookups need installed knowledge. Researching new products also requires a ready
research provider and internet access.

## Add the browser extension

In **More → Set up Kriko**, press **Prepare browser extension**. Then:

1. Open your Chromium browser's Extensions page.
2. Enable **Developer mode**.
3. Choose **Load unpacked** and select the folder shown by Kriko.
4. Open a product listing. Return to setup and check the browser connection.

The extension is loaded manually; these steps do not install a Web Store package.
After an app update, prepare the extension again and reload it in the browser.
Firefox development staging is available through the local API, but permanent
Firefox installation requires a Mozilla-signed package; the desktop setup panel
currently guides Chromium browsers.

## Check the complete flow

Ask for known problems with a product in Chat. Open a source, ask a follow-up,
then add a saved result to Compare. If the engine fails to connect, the app shows
a recovery screen. Example answers appear only after you explicitly choose demo
mode, which stays labeled on every screen.

## Update, stop, or remove

The app offers updates for installed Windows copies. Portable copies use the
download page: quit Kriko, replace the extracted app folder, and open it again.
User data remains in `%USERPROFILE%\.kriko`.

Use **Quit** in the system tray to stop the engine completely. Closing the window
can leave it running for the browser extension. Uninstalling keeps saved data;
export a snapshot from **More → Backup and restore** before manually deleting it.

> **An update fails.**
> Kriko still runs. Most updates replace only the engine: Kriko unpacks it into
> `%LOCALAPPDATA%\Kriko\engines`, restarts the engine and keeps the window open.
> If the new engine cannot start, Kriko sets it aside and starts the engine that
> came with the app. When a release changes the app itself, Update now runs the
> installer instead. If that fails, select **Quit** in the tray menu and start the
> installer again. You never need to uninstall first.

## Run from source

Python 3.13+ is required. From a checkout, run `tools/setup.sh`, then:

```bash
.venv/bin/python -m app.web
```

On Windows the interpreter is `.venv\Scripts\python.exe`. The local API defaults
to `http://127.0.0.1:8787`; this API is not the desktop window. Build the window
using [the desktop recipe](../kriko-ui/README.md).

For a problem report, include the app version, the affected screen, the agent/model
and a redacted error. Do not include API keys or private listing data.
