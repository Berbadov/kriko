# Kriko

[![version](https://img.shields.io/badge/version-0.3.3-1F4FFF?style=flat-square&labelColor=05070F)](https://github.com/Berbadov/kriko/releases/latest)

Kriko answers one question about the product you are looking at: *what is known
to go wrong with this exact one*. It runs on your computer — a Windows desktop
app and a browser extension — and keeps the source beside every finding.
Installed catalog lookups work offline. Research uses the agent or model you
choose, and a paid provider bills your own account.

**[Download the Windows installer](https://github.com/Berbadov/kriko/releases/latest/download/kriko-0.3.3-x86_64-setup.exe)** ·
[Browser extension](https://chromewebstore.google.com/detail/kriko/bdifnaggafjokndlpjgmlfappcoehdjb) ·
[Website](https://kriko.cc)

0.3.2 improves shared-access setup and connection reliability. The extension
panel opens on request; the [changelog](CHANGELOG.md) has the rest.

## Install

| Artifact | Use |
|---|---|
| `kriko-0.3.3-x86_64-setup.exe` | Per-user Windows installer; no administrator rights required. |
| `kriko-0.3.3-win64-portable.zip` | Extract the whole archive and open `kriko.exe`. |

1. Open Kriko, choose an agent in **More → Agents** and press **Check connection**.
2. Open **Catalogs → Find release catalogs** and install one, or import a
   `.kpack` file. Research also works with no catalog installed.
3. Add [Kriko to Chrome, Edge or Brave](https://chromewebstore.google.com/detail/kriko/bdifnaggafjokndlpjgmlfappcoehdjb),
   keep the desktop app running, and press the toolbar button or **Alt + K** on a
   product listing.

The installer is unsigned, so Windows may warn before it runs. The published
desktop scope is Windows x86_64; the source builds elsewhere. Details:
[Windows installation](docs/INSTALL_WINDOWS.md).

## What it does

- Asks about a product, compares options and continues the same conversation.
- Shows sourced problems, exact variants, specifications and coverage gaps —
  beside the listing through the extension, or in the app.
- Watches a price, ranks a shortlist to one pick, and asks later whether a
  purchase held up.
- Keeps catalogs, conversations and research history on your computer.

Kriko Agent is experimental and runs on your own provider keys; shared access and
the trial are in [shared access](docs/security/shared-access.md). The app's
screens and how to grow knowledge are in [Usage](docs/USAGE.md); matching, the
catalog lifecycle and layering are in [How it works](docs/HOW_IT_WORKS.md).

## Your data

Everything lives in `%USERPROFILE%\.kriko` on Windows (`~/.kriko` for a source
installation): `knowledge.sqlite` holds installed catalogs, `app.sqlite` holds
history, conversations and settings, and an update or uninstall keeps the folder.
Nothing leaves the machine except the question a research turn sends to the
provider you chose.

## Build and verify

Source work needs Python 3.13+, Node and a Rust toolchain for the native shell.

```bash
tools/setup.sh
cd kriko-ui && npm ci && cd ..
tools/gate.sh
```

The gate covers Python, the wheel, the extension and website tests, the desktop
app's TypeScript and behavior, and the native checks; a missing native check is
incomplete, not a passing release. See [Architecture](docs/ARCHITECTURE.md), the
[desktop build recipe](kriko-ui/README.md), and
[report a problem](https://github.com/Berbadov/kriko/issues).

## License

[MIT](LICENSE).

## Later

Our own inference service, a fine-tuned model, and statistical knowledge
extraction from forums.
