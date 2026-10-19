# Use Kriko

Kriko keeps product problems beside their evidence. Installed catalogs answer
locally. New research uses the selected agent and its account.

## Start and verify setup

Open **More → Set up Kriko**. Choose an agent, check its connection, obtain a
catalog, and prepare the browser extension. Complete a product question with a
source to verify the full research path. See [Windows installation](INSTALL_WINDOWS.md).

## Ask in Chat

Describe the product, exact variant, market and important constraints. Continue
in the same conversation when correcting a year, budget or preference. The latest
correction takes precedence. Conversation context and a compact saved memory keep
older requirements available, within the model's context limits.

For a comparison of pages, include their complete URLs. The host reader accepts
up to five supplied public links, text/HTML and text-bearing PDFs. It tries other
leads when leading search results cannot be read. Search snippets are leads;
fetched excerpts are the evidence used to ground an answer.

The attachment button reads text, Markdown, CSV, JSON and log files up to 12 KB.
The file text becomes part of the request sent to your selected provider. Image
and arbitrary binary attachments are not supported by desktop Chat.

Watch the activity trail to see searches and page-read outcomes. An unresolved
search request or an offer to start is not a completed task. When a decisive detail
is absent, the assistant should name it and explain the work it could finish.
Citation repair checks source provenance, and an additional review checks claims
against fetched excerpts and validates supporting quotations. An unverified
answer shows a warning. This review is fallible; inspect quotations for important decisions.

## Read a product result

Open a saved product to see problems, all available supporting quotations,
conditional applicability, assumptions, recorded use, coverage and specifications.
A saved date tells you when the check was recorded; current prices and stock may
need another research pass. No sourced problems is different from proof of no risks.

Ask a follow-up below the result. Answers can grow while research runs. **Stop**
cancels that job and retains useful partial text. A connection failure or provider
problem is shown with the question rather than silently disappearing.

## Compare options

Add up to four saved checks from product cards, product pages or History. Use Add
to search across saved checks and load older matches. Inspect each column's coverage
and variant before treating missing evidence as a difference.

Specification values retain their source and quote. Supported quantities such as
`2 kg` and `2000 g` compare equally while keeping their original wording. Problem
alignment uses a shared concept key when one exists and otherwise a normalized
title; different wording without shared identifiers still needs human interpretation.

Use **Differences only** to focus the view. Ask a question about the products below
the board. **Stop** cancels active comparison questions. If saving the board fails,
Kriko says that it is not saved and offers a retry.

## Browser and Queue

Load the prepared extension in your browser and open a listing. Its panel shows
installed knowledge or offers research for a new product. Follow the source behind
a reported problem. Send products to Queue to manage several checks; the number of
concurrent researches is controlled in Settings. Check provider identity before
starting work on a paid account.

## Catalogs

In **More → Catalogs**:

- **Find release catalogs** lists available knowledge and updates.
- **Import .kpack** installs a catalog artifact from your computer.
- **Update catalogs** follows the configured release index.
- **File saved Quick Looks** adds supported saved research to applicable drafts.
- **Research draft** asks the selected agent to research the described category.

An authored draft contains data only. Review it before pressing Install. Installed
catalogs can be enabled, disabled or rolled back where a previous revision exists.
Missing classification or identity evidence remains available for follow-up; filing
is not permission to invent a catalog assignment.

## History, settings and recovery

History searches the stored records and loads more results on request. Chat lists
support renaming, pinning, searching and Markdown export. Deleting a conversation
with active work is blocked until the work stops.

Settings controls providers, model choices, source preferences, language and market.
Measured spend includes conversation work where usage is reported; unpriced calls
remain explicitly incomplete. Provider bills can include work the app could not
measure, particularly an interrupted request.

**More → Backup and restore** exports saved work, settings, catalog revisions and
data-only drafts. Keys are excluded. Restoring a selected snapshot replaces current
saved state after a restart, retains previous database files, and leaves provider
key files unchanged. Stop active work before making or restoring a snapshot.

A failed engine connection shows Reconnect. Demo mode is an explicit choice and
always displays a banner. Mobile is a separate labeled prototype with simulated
research; its fixture results are outside the desktop stable-release scope.

## Buying help

Open **More**, then **For you**, and say what you need: how you use what you
buy, your budget, what you must have, what you avoid and distrust, and what
matters most to you. Kriko gives this to your agent with every question. You
can leave any of it empty.

On a product page the panel then shows **As a purchase**:

- **The price** against what Kriko has seen on that page before, with the
  line. A discount the history does not support is called out. With little
  history, Kriko says so and does not guess.
- **Watch this price** keeps an eye on the page. Choose the price you want to be
  told at. Kriko reads the page again a few times a day while it is running, with
  or without a browser open. A drop shows as a mark
  on the toolbar button and a card in the panel. To get a notification too, open
  the extension's options and press **Tell me when a watched price drops**.
- **How it fits you**, from what you said you need, and **Listing check**:
  the seller, the rating once few ratings are discounted, and which big words
  the page does not back up.
- **I bought this** starts the ledger. A few weeks later a small card on the next
  page Kriko reads asks if it held up, and your answer teaches Kriko what you
  regret.

In **Compare**, **Decide for me** ranks the products for you and names one,
with what it costs you and what would change the pick. The buttons under it ask
your agent to say it well, to argue it from three sides, to work out the cost of
owning each over three years, or to say if now is the time.

On a cart or payment page Kriko says if the item is not the one you researched,
if a shop it has seen sells it for less, if the page asks for a payment method
scams use, or if it shows no return terms. Both this and the marks on results
pages can be turned off on the extension's options page.

Everything here is kept in a file on this computer. **For you** lists what is
kept and has a button to forget each part.

### A phone, and watching while the computer is off

Kriko can watch a price when this computer is off if you run the relay in
`server/` (see its README: a small machine and a domain, for you alone). In **For
you**, under **Phone and relay**, enter the relay's address and its setup word and
press **Connect**. Press **Pair
a phone** to show the code that lets another device join, and subscribe to the
topic beside it in the ntfy app to get alerts on a phone.

The relay keeps sealed copies of your profile, purchases and watches. It cannot
read them. It is told a page only for a watch you turn on in the cloud (the
**Also watch while my computer is off** box in the panel, or **Watch in the
cloud** in For you), because a server that reads a page has to know the page. You
can keep the product's name from it.

## Development and acceptance

Use `tools/gate.sh` for the desktop checks and `tools/gate.sh mobile` for mobile
changes. A skipped native check is incomplete. [Release acceptance](RELEASE_ACCEPTANCE.md)
requires observing the packaged Windows journey with real providers before a
stable publication. Scripted agents and a successful build do not establish that.
