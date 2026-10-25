# Install Kriko on macOS

Kriko builds for Apple Silicon: M1 and later. The package is a disk image that
holds `Kriko.app`, and the app carries its own Python and engine, so nothing
else has to be installed. Intel Macs are not packaged yet; the source builds on
one, and `package-macos.sh` will produce an x86_64 disk image there.

## Install the desktop app

Open `kriko-<version>-arm64.dmg` and drag **Kriko** into **Applications**.

The build is signed ad-hoc, not notarized, so Gatekeeper holds the first open of
a downloaded copy. **Right-click → Open** and confirm, or remove the quarantine
flag once:

```bash
xattr -dr com.apple.quarantine /Applications/Kriko.app
```

The first start takes a few seconds longer than later ones: the engine is one
file and unpacks itself before it answers. The window says it is starting the
engine meanwhile.

Open the app. Its navigation contains **Chat**, **Compare** and **Queue**. Open
**More → Set up Kriko** for the remaining steps.

## Connect an agent

If a friend gave you an access code, open **More → Set up Kriko → Have an
access code from a friend?** Paste the whole code and its password, then press
**Use these keys**. Choose **Kriko Agent** in Agents and return to setup to
press **Check connection**. You do not need Python, another agent, or your own
API keys. Use the same release as the person who made your code.

Choose a coding agent, local model, or API agent in **More → Agents**. API keys
are managed in **More → Settings**; local model setup is in **More → Local model**.
Return to setup and press **Check connection**. This sends a short request to
the selected provider. A successful connection test checks answering, not full
source access; complete a sourced product question next.

## Install product knowledge

Open **More → Catalogs → Find release catalogs** and install a catalog. You can
also import a `.kpack` file. The app ships without a catalog; offline lookups
need installed knowledge. Researching new products also requires a ready
research provider and internet access.

## Add the browser extension

Install it from the Chrome Web Store:
<https://chromewebstore.google.com/detail/kriko/bdifnaggafjokndlpjgmlfappcoehdjb>.
Then open a product listing and return to **More → Set up Kriko** to check the
browser connection. The store package updates with the browser.
The panel opens when you press the toolbar button or **Alt + K**; it does not
open by itself as you browse.

A checkout can load the folder instead. In **More → Set up Kriko**, open
**Installing from a checkout instead** and press **Prepare extension folder**.
Then open your Chromium browser's Extensions page, enable **Developer mode**,
choose **Load unpacked** and select the folder Kriko shows. After an app update,
prepare the extension again and reload it in the browser.

## Check the complete flow

Ask for known problems with a product in Chat. Open a source, ask a follow-up,
then add a saved result to Compare. If the engine fails to connect, the app shows
a recovery screen. Example answers appear only after you explicitly choose demo
mode, which stays labeled on every screen.

## Update, stop, or remove

There is no in-app update on macOS yet. To update, choose **Quit** in the menu
bar icon's menu, open the newer disk image and replace **Kriko** in
**Applications**. Your data stays in `~/.kriko`, so it survives the replacement.

Closing the window hides it and the engine keeps running, because the browser
extension needs it. **Quit** in the menu bar icon's menu stops the engine and
the app. Dragging **Kriko** to the Trash removes the app; `~/.kriko` is yours to
delete, and **More → Backup and restore** exports a snapshot first.

## Build it yourself

On an Apple Silicon Mac with a Rust toolchain, Node.js and Python 3.13:

```bash
kriko-ui/package-macos.sh --arch arm64
```

It writes `kriko-ui/builds/kriko-<version>-arm64.dmg`. The recipe is also the
`macos-arm64` job in `.github/workflows/desktop.yml`, which uploads the disk
image as a workflow artifact. Set `KRIKO_MACOS_SIGN_IDENTITY` to a Developer ID
identity to sign with it instead of ad-hoc; notarization is not wired up.

For a problem report, include the app version, the affected screen, the agent/model
and a redacted error. Do not include API keys or private listing data.
