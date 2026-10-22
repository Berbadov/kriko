# Kriko

[![version](https://img.shields.io/badge/version-0.3.1-1F4FFF?style=flat-square&labelColor=05070F)](https://github.com/Berbadov/kriko/releases/latest)

Kriko researches what can go wrong with a product and keeps the sources beside
its findings. It runs on your computer, with a Windows desktop app and a browser
extension. Installed catalog lookups work offline. Research uses the agent or
model you select; a paid provider charges your own account.

- Ask about a product, compare options, and continue the same conversation.
- Inspect sourced problems, exact variants, specifications and coverage gaps.
- Check a listing through the extension, then open the saved result in the app.
- Say what you need and get buying help: price history, a watched price, one
  named pick from your shortlist, and a later check on whether it held up.
- Keep catalogs, conversations and research history on your computer.

Contents: [Install](#install-and-start) · [Agents](#working-with-agents) ·
[Buying help](#buying-help) · [Catalogs](#catalogs-and-saved-work) ·
[Your data](#your-data) · [Build and verify](#build-and-verify)

Version 0.3.1 marks Kriko Agent as an experimental preview, corrects Mercury key
testing and removes the duplicate DeepSeek key row. Version 0.3.0 introduced
product cards, source quote chips, evidence sensitivity, usage meters, daily caps
and provider settings. See the [changelog](CHANGELOG.md) for the release notes.

## Install and start

Download the Windows x86_64 setup EXE or portable ZIP from the
[latest release](https://github.com/Berbadov/kriko/releases/latest).

| Artifact | Use |
|---|---|
| `kriko-0.3.1-x86_64-setup.exe` | Per-user Windows installer; no administrator rights required. |
| `kriko-0.3.1-win64-portable.zip` | Extract the whole archive and open `kriko.exe`. |

The installer is unsigned; Windows may show a SmartScreen warning. The desktop
source can be built on other systems, but the published desktop release scope is
Windows x86_64. Mobile is a separate prototype with fixture research, outside the
stable desktop research promise.

1. Open Kriko and select **More → Set up Kriko**.
2. Choose an agent in **Agents**. Return to setup and press **Check connection**.
3. Open **Catalogs → Find release catalogs**, or import a `.kpack` file. Public
   research also works without an installed catalog when a research provider is ready.
4. Install [Kriko from the Chrome Web Store](https://chromewebstore.google.com/detail/kriko/bdifnaggafjokndlpjgmlfappcoehdjb)
   in Chrome, Edge or Brave. Keep the desktop app running, open a product listing,
   and press the Kriko toolbar button or **Alt + K**. The store handles extension updates.
5. Ask a product question in **Chat** and inspect a source before making a decision.

The main navigation is **Chat**, **Compare**, and **Queue**. **More** contains setup,
agents, local models, catalogs, sites, history, settings, and backup/restore.
The extension needs the desktop app. **More → Set up Kriko** checks its connection;
manual folder loading is only needed for a development checkout. See the
[Windows installation guide](docs/INSTALL_WINDOWS.md) for details.

## Working with agents

Kriko Agent is an experimental preview, marked **Soon**. Its Mercury 2.5 model
and DeepSeek Search/Fetch use your own provider keys on this computer. Downloads
include no shared Kriko credentials; the app does not provide a hosted research
account. Two things let someone else use your keys anyway, and both are yours to
give:

- **An access code and a password** (Settings → Shared access). You make the
  code from the keys saved on your computer, send it and a password to a friend
  in two separate messages, and their Kriko Agent runs on your keys. The code is
  sealed with the password *and* with a secret inside the shipped app, so the
  password is worth nothing outside Kriko; no key is ever written in the clear,
  and on Windows the opened grant is bound to the Windows account that opened
  it. Replace your keys at the providers to stop every code working.
- **A trial**, if the build you installed carries one: a few Kriko Agent
  questions for someone who has been given nothing, counted on their own
  computer. What it can and cannot protect is in
  [shared access](docs/security/shared-access.md) — the short version is that a
  trial key belongs at the provider with a spend limit on it.

An ordinary request starts the work. Agents receive shared instructions to carry
it through, use another source when a read fails, preserve your constraints and
ask only for details that materially change the answer. Empty offers receive a
repair attempt; unanswered tool requests cannot become completed answers. A
research turn is bounded on every side — its own deadline, a whole-request limit
on each search, a bounded wait for the retrieval pool — and says what it is doing
while it does it, so a slow search is visible rather than a frozen step. Buying
answers identify the product and its parts before they name a candidate or a
seller, and say which parts they could not identify.

Each agent also chooses whose web search it uses (Settings → Agents): its own
tools, which is the default, or Kriko's — Kriko searches and reads the pages and
then checks every quote against a page it fetched itself. Kriko's is the
experimental one, and the one to choose when checked quotes matter more than the
agent's own reach.

Chat reads multiple supplied links, can continue a search, and keeps older user
requirements in conversation context. The local reader supports public HTML/text
pages and text-bearing PDFs. You can attach a text, Markdown, CSV, JSON or log
file up to 12 KB; its text is included in your message to the selected provider.

Product and Compare questions show progress and support stopping the actual job.
Detailed follow-ups can use structured answers. Missing evidence remains unknown;
a low problem count does not establish safety. Chat checks citation provenance
and reviews consequential claims against fetched excerpts, with a repair attempt
or a visible warning when support is missing. Model review can still miss errors;
inspect the underlying evidence before making a decision.

## Buying help

Open **More → For you** and say how you use what you buy, your budget, what you
must have and what you distrust. Kriko gives this to your agent with every
question; every part is optional, listed there and can be forgotten.

On a product page the panel shows **As a purchase**: the price against what
Kriko has seen on that page, a discount the history does not support, how the
product fits you, and a listing check (seller, rating, claims the page does not
back up). **Watch this price** rereads the page a few times a day while Kriko is
running; a drop marks the toolbar button. **I bought this** starts a ledger, and
a few weeks later Kriko asks whether it held up. In **Compare**, **Decide for me**
ranks your shortlist and names one pick with its cost and what would change it.
A cart or payment page is checked for a different item, a cheaper shop Kriko has
seen, scam payment methods and missing return terms.

Everything here stays in a file on this computer. To watch a price while the
computer is off, you can run your own small relay (`server/`, see its README);
it keeps sealed copies it cannot read. Setup is in [Usage](docs/USAGE.md).

## Catalogs and saved work

**More → Catalogs** discovers release catalogs, imports artifacts, updates installed
knowledge, files saved Quick Looks, and researches new data-only drafts. Review a
draft before installing it. Catalog definitions and evidence gates are shared by
the app and MCP tools; new product categories are data, not changes to the engine.

History search runs over the saved store and loads additional results on request.
Compare shows up to four checks with sourced specifications, applicability,
coverage, assumptions and saved dates. Supported numeric units are normalized when
checking whether specifications differ; original values remain visible.

## Your data

The default data folder is `%USERPROFILE%\.kriko` on Windows and `~/.kriko` for
source installations. Catalogs live in `knowledge.sqlite`; history, conversations
and settings live in `app.sqlite`. An update or uninstall keeps this folder.
Research sends questions, attached text and relevant page excerpts to your selected
provider. Provider keys are managed separately in Settings.

**More → Backup and restore** exports a ZIP snapshot of saved work, settings,
installed catalog revisions and data-only drafts. Provider key files are excluded.
Restore validates and stages the snapshot, then applies it when the engine restarts;
it keeps previous databases beside the restored files. Stop active research first.

The app offers a newer release when one is available. Installed Windows copies can
update in place; portable copies are replaced from the download page. Closing the
window can leave the engine running for the extension; use **Quit** in the tray to
stop it completely.

## Build and verify

Source work needs Python 3.13+, Node, and a Rust toolchain for the native shell.

```bash
tools/setup.sh
cd kriko-ui && npm ci && cd ..
tools/gate.sh
```

The gate covers Python, the wheel, extension/site tests, desktop behavior and
TypeScript/lint, and native checks. A missing native check is incomplete, not a
passing release. Mobile changes additionally use `tools/gate.sh mobile`.

To see what an agent search and a quick search each do, run them together:
`python -m app.livesearch "Brand Model" --agent claude-code` writes a report of
the queries, pages and sites per lane (see [Usage](docs/USAGE.md)).

For separate web research experiments, use the [product search benchmark](docs/PRODUCT_SEARCH_BENCHMARK.md).
It compares answer quality, latency, tokens and cost, with plain sortable tables and expandable request logs.

- [Windows installation](docs/INSTALL_WINDOWS.md)
- [Usage](docs/USAGE.md)
- [Architecture and development](docs/ARCHITECTURE.md)
- [Desktop build recipe](kriko-ui/README.md)
- [Stable release acceptance](docs/RELEASE_ACCEPTANCE.md)
- [Readiness findings](docs/BETA_READINESS_AUDIT.md)
- [Changelog](CHANGELOG.md)
- [Report a problem](https://github.com/Berbadov/kriko/issues)

## License

[MIT](LICENSE).

## Milestones

Not in order.

- Releasing our own inference service
- Fine-tuning a model for Kriko
- Statistical knowledge extraction from forums
