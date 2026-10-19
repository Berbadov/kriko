# Use Kriko

This guide starts the app, connects an agent, checks a listing, and grows a
catalog. [How Kriko works](HOW_IT_WORKS.md) explains the mechanism.

## Before you start

| For | You need |
|---|---|
| The desktop app | Nothing. The app contains its own Python, and a lookup needs no network. |
| Source work (the command line, the pipeline, the tests) | Python 3.13 or newer. |
| Research | An agent, a model on your computer, or a key for a paid API. A lookup needs no key. |

## 1. Start the app

Install the app and open it. [The install guide](INSTALL_WINDOWS.md) gives the
steps. From a source checkout:

```bash
.venv/bin/python -m app.web            # http://127.0.0.1:8787
curl http://127.0.0.1:8787/api/health  # {"ok":true,...}
```

If you close the window, the app hides and the engine continues, because the
browser extension needs it. The tray menu holds **Open Kriko** and **Quit
Kriko**. The tray tooltip says if the engine is ready, if it starts, or if it
stopped.

> **Port 8787 is not free.**
> Open **Browser extension**. Enter a free port and press **Save port and
> restart engine**. Then set the same address in the options of the extension,
> for example `http://127.0.0.1:8790`. Kriko keeps this choice.

## 2. The screens

| Screen | Group | Contents |
|---|---|---|
| Home | Check | The totals, the work that waits, the latest checks, and the app update |
| Run | Check | The steps of the selected check, the agent lanes, the decision card, and the log |
| History | Check | The past checks, with a search box, filters, and paging |
| Compare | Check | Up to four saved checks side by side, with the differences |
| Chat | Check | A conversation with your agent, with the sources beside each answer |
| Browser extension | Check | The steps to prepare the extension, the port, and the switches |
| Overview | Knowledge | The catalogs to install, the installed catalogs, the gaps, and **File quick looks** |
| Browse | Knowledge | The products, the problems, and the sources of a catalog |
| Sites | System | The sites that Kriko can read, and the trust grade of each |
| Activity | System | The live work: what needs you, and what runs now |
| Agents | System | The installed agents, their state, their model, and their permissions |
| Benchmark | System | The measurements of your models on fixed cases |
| Local LLM | This install | The model server, the models, and their settings |
| Settings | This install | General, shortcuts, keys, privacy, the tour, and the erase |
| About | This install | The version, the update, and the licences |

## 3. Connect an agent

An agent is a program that reads the web for you. Open **Agents** and select an
agent. Then press **Check connection**. Kriko runs a real test and shows each
step of it.

| State | Meaning |
|---|---|
| Ready | The agent can run a check. |
| Needs sign-in | The agent is installed, but you must sign in to it. |
| Not installed | Kriko found no agent program on this computer. |

Kriko gives the agent a research skill and a set of tools. The skill is
assembled from the installed catalogs and served at `GET /api/agent-skill`. The
tool list is in `src/app/mcp_server.py`. Kriko refuses a finding with a
quotation that is not in the page that the agent names.

## 4. Use a model on your computer

A local model answers on your own computer and costs nothing extra. Open
**Local LLM** and press the setup key on the server card. Kriko installs the
model app, downloads the recommended model, and selects it. The download shows
its byte count.

The model table shows the parameters, the context window, and the fit in your
graphics memory. **Browse downloadable models** adds another model. A download
can be cancelled from its progress card.

A local model cannot search the web alone. Kriko uses a hosted keyless search
until a local search service is available. A small model can miss a detailed
specification. The **Benchmark** screen measures your models on fixed cases.
These measurements are not a guarantee.

### Use vLLM on Windows

Kriko discovers vLLM at `http://127.0.0.1:8000` and uses its OpenAI-compatible
`/v1/chat/completions` API. Set the endpoint in **Local LLM**, select a model
from the server's model list, and save. Kriko does not control vLLM's loader or
report its GPU use; choose GPU settings and context when starting vLLM. vLLM's
official installation guide says Windows is not supported natively, so run it
in WSL 2. WSL localhost forwarding usually makes the default endpoint available
to Kriko at `127.0.0.1:8000`.

In the WSL Linux shell, install vLLM in a fresh environment as described by its
[official GPU installation guide](https://docs.vllm.ai/en/stable/getting_started/installation/gpu/):

```bash
uv venv --python 3.12 --seed --managed-python
source .venv/bin/activate
uv pip install vllm --torch-backend=cu130
vllm serve Qwen/Qwen3-8B --host 127.0.0.1 --port 8000
```

Replace the example with a supported model that fits your GPU; the official
guide currently lists NVIDIA GPUs with compute capability 7.5 or newer. vLLM's
current guide also documents `--torch-backend=auto` and release-specific CUDA 13.0
wheels. CUDA 13 requires an NVIDIA driver from the R580 family or newer; check
the [CUDA 13 release notes](https://docs.nvidia.com/cuda/archive/13.0.0/cuda-toolkit-release-notes/)
and install the current Windows NVIDIA driver for WSL. The CUDA version shown
by `nvidia-smi` is the maximum supported by the driver, not the toolkit version
that must be separately installed in WSL. Keep the server bound to loopback;
Kriko does not currently send a vLLM API key.

## 5. Check a listing

1. Open a listing in your browser.
2. Open the Kriko panel. The panel appears after about two seconds.
3. Read the known problems. Open a problem to read its sources and its
   quotations.

The panel needs a catalog for the product. A new install has no catalog.

If no catalog covers the product, press **Quick look** in the panel. Kriko asks
your agent to search and read. The result keeps its sources, and you can ask
more questions in the panel. Kriko saves each quick look in your history.

To make a quick look part of a catalog, open **Overview** and press **File
quick looks**.

> **The panel is missing on a page.**
> Open **Sites**. The screen says if the site needs a permission, or if no
> adapter reads the site.

### Buying help

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
`server/` (see its README: a small machine and a domain). In **For you**, under
**Phone and relay**, enter the relay's address and press **Connect**. Press **Pair
a phone** to show the code that lets another device join, and subscribe to the
topic beside it in the ntfy app to get alerts on a phone.

The relay keeps sealed copies of your profile, purchases and watches. It cannot
read them. It is told a page only for a watch you turn on in the cloud (the
**Also watch while my computer is off** box in the panel, or **Watch in the
cloud** in For you), because a server that reads a page has to know the page. You
can keep the product's name from it.

## 6. Research in the app

**Run** starts a deeper check for one product. Select the product and the
agent, then press **Start check**. The screen shows the phases, the lanes of
the agents, and the decision. You can stop a run and start it again.

**Chat** answers a question in a conversation. The answer keeps its sources.
Each conversation keeps its own draft. Press Stop, Retry, or Copy near the
answer.

**Find something to buy.** Ask Chat for a product, a part, or a seller. Name the
product exactly. Give the model, the year, and the engine or variant. The answer
then follows four rules:

1. Kriko reads popular sites first. A site that Kriko does not know is marked
   *unrecognised*.
2. A code is *confirmed* when two trusted sites print it. A code on one site is
   a *single source*.
3. A seller on a marketplace is judged by the seller. The answer shows the name
   and the score from the page. If the page shows neither, the answer says the
   seller is unknown.
4. A claim such as "official dealer" is shown as the claim of the page. It is
   not proof.

To add or change a site, create the file `~/.kriko/sellers.json`. Use the same
shape as the file `src/app/sellers.json`, and list only your own sites. Your
entry replaces the tier of the same domain. Restart Kriko after the edit.
Always read the page of the seller before you pay.

**Compare** puts up to four saved checks side by side. It shows the
specifications and the known problems, cell by cell, with a mark for each
difference. You can ask a follow-up question and keep reading.

## 7. Manage the catalogs

**Overview** lists the catalogs of the release. Press **Install** to add one.
A switch turns a catalog off without removing it.

Kriko keeps the installed catalogs current each week. You can also install a
file by hand:

```bash
kriko install <file.kpack>
```

**Browse** shows the products of a catalog, their problems, and their sources.

**Settings** holds your keys, your preferences, and the tour. The erase key
removes your data after a second confirmation.

## 8. The command line

A command that reads only the store needs no server. The other commands attach
to a running app or start an engine for one command. The options `--url` and
`--no-start` control this.

| Command | Function |
|---|---|
| `kriko packs`, `install`, `uninstall`, `enable` | Manage the installed catalogs |
| `kriko build packs/<name>` | Build a catalog folder into a `.kpack` file |
| `kriko lookup key=value` | Ask the installed catalogs about a product |
| `kriko agenda`, `brief`, `submit` | What to research next, the brief of one product, and the filing of findings |
| `kriko prefs`, `costs` | The selected provider, the measured spend, and the next estimate |
| `kriko sites [register HOST \| forget HOST]` | The sites that this installation can read, and the teaching of a new site |
| `kriko verify [--list]` | Read the sources of the installed problems again |
| `kriko drafts [list \| show \| amend \| build \| install \| discard]` | The catalog drafts of your agents |
| `kriko operations`, `bench`, `agent-bench` | The live feed of agent work, and measurements of the models |
| `kriko tui` | The operator console |

## 9. Add a product to a catalog

The usual path costs nothing extra. Give the product to a connected agent:

```text
use the kriko-research skill to research <product>
```

1. The agent looks up the variants. Kriko answers with what the catalog
   covers and what it does not.
2. The agent submits the findings, each with a quotation and a source.
3. Kriko proves each quotation. A good finding becomes part of a draft on
   disk.
4. You read the draft and install it.

Do not send a refused finding again with different words. A refusal names the
correction. Kriko refuses:

- a quotation that is not in the page that the agent read
- a figure with no source
- a value that nobody can derive
- a line-up that does not agree with the category
- a row that the bar of the catalog excludes

**The manual path** is what the agent drives. The stages are the same for every
catalog.

```bash
python -m app.pipeline.ledger_run acquire --part <code>
python -m app.pipeline.ledger_run all
kriko build packs/<name>
kriko packs
```

| Command | Function |
|---|---|
| `python -m app.pipeline.ledger_run` | The stages: acquire, backfill, extract, resolve, cluster, verdict, export, report, remediate, all |
| `python -m app.pipeline.ledger_run remediate --dry-run` | Fill the gaps that the coverage report names. `--max-usd` limits the spend. |
| `python -m app.pipeline.panel` | The spend, the cost to finish, the coverage, and the recent runs |
| `python -m app.pipeline.process --help` | One product from end to end, in the identity keys of that catalog |

The stages write YAML. Kriko serves nothing until you build the catalog and
install it. The pipeline owns the status of a row. Do not edit a status by
hand.

## 10. What the reader sees

| Shown as | When |
|---|---|
| **Confirmed** | At least one source is from a confirming trust tier. The card shows a relevance number. |
| **Reported** | Every other problem. The card shows its sources and no number. |

The pipeline keeps a problem only with quotations that it proved in the page
that it read. The engine serves the problems of the catalog and does not read
the quotations again. The panel shows the strength from the trust tier of the
sources.

## 11. Examine the store

If you have the `sqlite3` command:

```bash
sqlite3 ~/.kriko/knowledge.sqlite "SELECT pack_id, version, built_at FROM packs;"
sqlite3 ~/.kriko/knowledge.sqlite "SELECT subject_id, kind FROM subjects LIMIT 20;"
```

The route `/api/health` reports both database files. The full payload of each
past check is in `logs/analyses.jsonl`.
