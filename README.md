# Kriko

[![version](https://img.shields.io/badge/version-0.2.1-1F4FFF?style=flat-square&labelColor=05070F)](https://github.com/Berbadov/kriko/releases/latest)
[![platform](https://img.shields.io/badge/platform-Windows_x64-1F4FFF?style=flat-square&labelColor=05070F)](https://github.com/Berbadov/kriko/releases/latest)

Kriko shows what can go wrong with a product. It puts this knowledge next to
the listing that you read.

A listing tells you what a product offers. Kriko tells you what can go wrong
with that product, where the information came from, and what to examine before
you decide.

- **Read beside a listing.** The browser extension shows the known problems and
  their sources on the page.
- **Follow the sources.** Open the page behind a problem and read the
  quotation.
- **Research a new product.** Ask your agent to search and read. Then ask more
  questions in the same panel.
- **Compare your options.** Put products together and compare what is known
  about each one.
- **Keep your knowledge.** Save research as a catalog. Catalogs and your
  history stay on your computer.

A lookup in an installed catalog needs no network and no key. Research needs
the internet and the agent or model that you select. A paid provider bills your
own account.

## What's new in 0.1.2

- **Chat answers are formatted.** A bold term is bold. A bullet list is a list.
  A table is a table. A link opens the page it names. You can drag over an
  answer and press Ctrl+C to take the words out.
- **A product card under an answer.** When a turn reads your catalogs, the
  answer carries a card for each product it found, with **Open**, **Add to
  Compare** and **Read again**.
- **Agents** is now the home for every way of answering a question: the coding
  agents on this machine, the local model, and the paid APIs you hold a key
  for. **Local LLM** left the rail and keeps its own screen.
- **The model store is a list**, one full-width row for each model with one
  primary action.
- **The light theme is correct.** The hero band keeps its own colours in both
  themes, and a new edge token separates two surfaces.
- **The agents are faster.** The plane decision fell from 1114 ms to 264 ms on
  a cold start, and a request on the loopback address from 17.19 ms to 1.43 ms.
- **Kriko can work out how to read a new site** with the local model, from the
  page data the extension already collects.

[The changelog](CHANGELOG.md) holds the full list and the known limits.

## Download

Choose a file from the [latest release](https://github.com/Berbadov/kriko/releases/latest).

| File | Use |
|---|---|
| `kriko-0.2.1-x86_64-setup.exe` | Install Kriko on Windows. You do not need administrator rights. |
| `kriko-0.2.1-win64-portable.zip` | Use Kriko on Windows without an installer. Extract the file and open `kriko.exe`. |

The app contains everything that it needs to start. It contains no catalog.
Install a catalog after the first start.

The build is unsigned. Windows may show a SmartScreen warning on the first
start. Select **More info**, then **Run anyway**.

## Start

1. Install Kriko. On Windows, use the MSI or the portable ZIP. On macOS, open
   the disk image and move `Kriko.app` to **Applications**.
2. Open Kriko. The first start shows a setup with four steps.
3. Install a catalog. Open **Overview**, in the group **Knowledge**. The screen
   lists the catalogs of this release. Press **Install**.
4. Add the browser extension. Open **Browser extension**, in the group
   **Check**. Press **Stage**. Then follow the steps on the screen.
5. Open a product listing. Open the Kriko panel and read the known problems.

[The install guide](docs/INSTALL_WINDOWS.md) and [the usage guide](docs/USAGE.md)
give the full steps.

## Catalogs

A catalog is the product knowledge of one product category. It contains the
products, the known problems, and the sources. Kriko checks a listing against
the installed catalogs.

Kriko publishes a catalog as a `.kpack` file. The app keeps the installed
catalogs current each week. A catalog cannot answer for a product that it does
not cover.

If no catalog covers a product, use **Quick look** in the panel. Kriko asks
your agent to search and read. The result keeps its sources, and you can ask
more questions. Kriko saves every quick look in your history.

To make a quick look part of a catalog, open **Overview** and press **File
quick looks**.

## Research

Research needs an agent or a model. Open **Agents**, in the group **System**,
and select one. Then press **Check connection**.

For a model on your own computer, open **Local LLM**, in the group **This
install**. For a paid API, add its key in **Settings**.

Kriko starts a paid API only after you select it. A run that names no provider
uses the first provider that is ready, and the log of the run names it.

## Your data

Kriko keeps its data on your computer.

| Data | Windows | macOS |
|---|---|---|
| Catalogs | `%USERPROFILE%\.kriko\knowledge.sqlite` | `~/.kriko/knowledge.sqlite` |
| History and settings | `%USERPROFILE%\.kriko\app.sqlite` | `~/.kriko/app.sqlite` |

An update or an uninstall keeps this folder. To remove all data, delete the
folder.

A lookup runs on your computer. Research sends the question and the pages that
Kriko read to the provider that you selected.

To stop Kriko completely, select **Quit** in the tray menu. If you only close
the window, the engine continues, because the browser extension needs it.

Kriko looks for a newer version at each start and offers it on the **Home**
screen. Press **Install and restart**. The app updates only the Windows x86_64
MSI. For the portable ZIP and the macOS app, download the new file and replace
the old one.

## Help

- [Install Kriko on Windows](docs/INSTALL_WINDOWS.md)
- [Use Kriko](docs/USAGE.md)
- [How Kriko works](docs/HOW_IT_WORKS.md)
- [Report a problem or ask for a feature](https://github.com/Berbadov/kriko/issues)

If the panel says that Kriko does not run, open the app first. After an update,
prepare the browser extension again and reload it in the browser.

## Build from source

The engine, the command line, and the local API run from source on Windows,
macOS, and Linux. [The architecture guide](docs/ARCHITECTURE.md) gives the
commands and the tests. [The desktop app guide](kriko-ui/README.md) gives the
installer recipe and the macOS build.

Source work needs Python 3.13 or newer.

## License

Kriko is open source under the [MIT License](LICENSE).
