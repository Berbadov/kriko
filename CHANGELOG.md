# Changelog

Reader-visible changes for each release. Newest first. Published versions are
immutable; a correction is a newer version.

### Unreleased

- **Chat asks before it answers.** When one detail would change the answer — a
  tyre size, a model year, an engine, the market you buy in — Chat asks for it
  first, with choices you press, on whichever agent you chose. A second
  question can follow the first; the same one is never asked twice, and a
  detail written in Chat settings is not asked at all.
- **Chat settings.** Under More, Chat, write what Kriko should remember about
  you — your car and the size on it, the shops you trust, a budget — and turn
  on product-only answers: a short list of products with links and at most two
  warnings, instead of a long answer.
- **Links in a buying answer.** A request for something to buy searches the web
  whichever words it uses, and the answer carries the pages Kriko read as
  links even when the agent left them out — the local model included.
- **An answer stops looking unfinished.** Once the text is complete its last
  words stop fading and Copy and Retry appear at once, instead of waiting for
  the conversation's follow-up suggestions. The activity list no longer
  redraws its lines on every poll.
- **The panel opens where Kriko knows the site.** It used to come up by itself
  on any product-like page of a site nothing read, and stay quiet on the sites
  Kriko does read. A known site now opens its own answer once per session; an
  unknown site is opened from the toolbar, where Learn this page waits.

### 0.2.6

- **Fixes from a bug hunt over everything below.** A price with two numbers in
  it ("from 10 to 30", "-50% 199,90 TL") is no longer read as one glued price,
  and a budget or a review count written the way a shop prints it ("15.000",
  "1,234") is read as the number it is. A watched page keeps its address as it
  was written. Forgetting all your purchases or watches stays forgotten on a
  paired device. A cart page's lines are counted once, the price beside a
  product's name is the one it reads and not a price in the header, and a shop
  that changes page without loading is read again.
- **Safer fetching.** A page that redirects to this computer or to your own
  network is refused, as is the shared address range used by Tailscale and some
  clouds. A page built to stall the reader (a hundred thousand unclosed tags)
  no longer takes minutes to read. One page's broken data fails alone, in the
  app and on the relay.
- **The relay and sync.** The relay refuses a large body before reading it. A
  long product name, a large purchase history or one page the relay will not
  watch no longer stops the rest of a sync, and a stopped watch is stopped
  first.
- **The app.** The lists and the budget in For you keep what you type. A second
  restore keeps the state just before it. Saved checks are found by words with
  letters such as ü and ı. A failed settings save keeps its message. Start Ollama
  says why it could not. The queue and Compare no longer call a job failed
  because one read of it was slow.

- **Kriko knows what you need.** Under More, For you, say what you buy and
  use things for, your budget, what you must have, what you avoid and distrust,
  and how much price, quality, lasting and repairability matter to you. Kriko
  gives that to your agent with every question, so the advice is for you and not
  for everyone. Nothing is added to a question until you say something.
- **Kriko learns what you regret.** Press I bought this on a product page, or
  add it under For you. A few weeks later Kriko asks if it held up, in a small
  card on the next page it reads (once a day at most, one purchase at a time),
  and a number on More in the app. You can answer or ignore it. Your answers
  go to your agent as lessons, so a brand that let you down is not recommended
  the same way twice.
- **A price is judged against its own history.** Every product page you read
  adds a price to a history kept on this computer. The panel says if this is the
  lowest Kriko has seen, the usual price or a high one, draws the line, and says
  when a discount does not hold up (an old price that was never charged, or a
  sale at the normal price). It says it has too little history before it says
  anything it cannot support.
- **Watch a price.** Press Watch this price and choose the figure. Kriko reads
  the page again a few times a day, on the engine's own clock (every half hour it
  checks which watched pages are due, and a page is read at most every six
  hours), whether or not a browser is open. It tells you when the price falls: a mark on the
  toolbar button, a card in the panel and, if you allow notifications on the
  extension's options page, a notification. A shop that draws its price with
  script cannot be read in the background, and the watch says so.
- **A listing is checked against itself.** The panel shows who sells it (a
  marketplace listing with no named seller, a payment method scams use), how
  the rating looks once few ratings are discounted, and which big words the page
  does not back up (waterproof with no rating, original from a seller no one
  vouches for, certified with no certificate).
- **Kriko picks.** In Compare, Decide for me ranks your products for you from
  their known risks, price history, seller, claims and what you told Kriko, and
  names one, with what it costs you, what would change the pick and what to check
  first. Your agent can then say it well, make a sceptic, a bargain hunter and a
  durability fanatic argue it, work out the cost of owning each over three years,
  or say if now is the time. The pick is the same whichever agent is connected.
- **A look before you pay.** On a cart or payment page Kriko says if the item
  is not the one you researched, the same product is cheaper at a shop it has
  seen, the page asks for a payment method scams use, or shows no return terms.
  It can be turned off on the extension's options page.
- **Results pages show what breaks your needs.** Once you have told Kriko what
  you need, products on a results page that mention what you avoid, or cost more
  than your budget, carry a small mark. It can be turned off on the options page.
- **A relay for your phone, and for watching while the computer is off.**
  `server/` holds a small server you run yourself (a few dollars a month). Under
  More, For you, Phone and relay, connect to it and pair a phone with a code. Your
  profile, purchases and watches are kept on it as copies sealed on your devices
  with a key it never receives, so a phone and this computer agree. For a watch
  you turn on in the cloud, the relay reads the page itself and pushes an alert to
  your phone through ntfy when the price crosses your target. One relay serves one
  reader (the first device with the relay's setup word claims it). It has to be told
  that page: hashing an address cannot hide it from whoever fetches it, so it is
  per watch, kept encrypted at rest, and you can keep the product's name from it.
  Nothing is sent to a relay you have not connected, and a watch you leave off
  stays on this computer.
- **See and forget what is kept.** For you lists everything Kriko remembers
  about you as a buyer, where it is, and a button to forget each part.
- **The engine updates without the installer.** Update now used to run the whole
  installer over a running Kriko, and when that went wrong the cure was an
  uninstall and a fresh install. A release now also carries the engine alone.
  Kriko unpacks it into a folder of its own, checks it against the release's
  checksums, and restarts only the engine. The window stays open, nothing is laid
  over anything, and the installer is not run. If the new engine cannot start,
  Kriko sets it aside and starts the engine that came with the app, so a bad
  update costs a restart, not a reinstall. A portable copy gets engine updates
  too. A release that needs a newer app than yours still offers the installer.
- **Uninstall removes the staged engines too.** They live in
  `%LOCALAPPDATA%\Kriko\engines`. An install keeps one that is newer than the
  engine it carries.
- **The local model starts Ollama for you.** Asking the Local model a question
  while Ollama is installed and closed no longer fails with "Nothing answers at
  127.0.0.1:11434". Kriko starts Ollama, waits for it, and runs the question.
  Nothing is started for a reader who did not pick the Local model, and a server
  you pointed Kriko at yourself is left alone.
- **Agents advise.** Chat, the web answer, follow-up questions and Compare now
  tell the agent to name specific products or part numbers with a caution,
  and never to answer with only search terms, "check the specifications" or "I
  cannot recommend a product". A bare product phrase such as
  "Megane 4 1.5 blue dci 2020 yag ve filtre seti" is a buying request and goes
  to the web, where before it was answered from memory.
- **Learn this page is offered where a page cannot be read.** A page that
  Kriko could not read on a site it has an adapter for used to show "Unable to
  read this page" and nothing else. One refused selector in an adapter could
  stop the whole read; each reader now fails alone and the rest still answer. The
  panel shows what went wrong and a Learn this page button under it, and
  re-reads the page when it has learned it.

### 0.2.5

- **An update now says what version it is.** After 0.2.4 was installed over
  0.2.3, Kriko kept reporting 0.2.3 and kept offering 0.2.4 to itself, so Update
  now reinstalled the same thing. The installer laid the new program over the
  old one and left the old one's version record beside it, and Kriko read the
  wrong one. Kriko now reads the newest version record it finds, and the
  installer clears the engine's own folder before it installs.
- **Uninstall removes the engine's folder.** The same leftover files were not on
  the uninstaller's list, so the folder stayed behind and the uninstall could
  fail. The uninstaller now clears that folder too, after it stops Kriko. Your
  catalogs and chats are not in it: they stay in `.kriko` in your profile.

If you are on 0.2.4 and it still shows 0.2.3 in Settings, About, quit Kriko from
the tray and run the 0.2.5 installer once by hand. That install removes the old
record.

### 0.2.4

- **Kriko starts agents when you need them.** Opening the app no longer
  launches your coding agents or asks them for their model lists. The window
  reads a short list of the agents you have, and the full discovery happens when
  you open Settings. An agent that sits idle is now closed after 90 seconds
  (20 on a machine with little memory), and Kriko keeps at most one warm. Closing
  an idle agent no longer holds up the one you are using. The agent picker
  refreshes when you change a setting or a key, without resetting a conversation.
- **A local model no longer shows its thinking or a raw search request.** Some
  local models printed their reasoning, or answered a request to search with a
  block of structured text. Kriko now hides the reasoning, reads the common
  shapes of a search request and runs the search. If a model's request cannot be
  read, Kriko searches for your own words.
- **Use any OpenAI-compatible API as an agent.** Add your key in Keys, and the
  endpoint and the model ID in Settings, Research. The agent can use the Exa or
  Tavily search you chose.
  Your key is never shown again, and a reply that cannot be read is refused
  instead of guessed.
- **Choose the market and the language.** Settings, Research, has a language for
  answers, a language for searches and a market (a country or the European
  Union). Chat, quick looks, research and follow-up questions all use them. The
  agent is also told to match the length of the answer to what is at stake, to
  require exact fit for a part (a PC part or a vehicle part), and to report what a
  forum alleges as an allegation, not as seller evidence.
- **See what Kriko searched and read.** A run lists the exact addresses it
  searched, how many pages it tried and how many it read. These are three
  numbers, not one. A cancelled read is not counted as read. The log of a run
  stays with the conversation when you open it again.
- **A finished queue clears, and keeps its results.** When every research in a
  batch is done, the queue empties. The saved checks stay in your history, and
  anything waiting, paused, failed or added later stays in the queue.
- **Chats get a title, and suggest what to ask next.** The agent names a new
  conversation and offers up to three related questions. A click puts one in the
  message box, where you can edit it before you send. Your answer is saved first,
  and a title you chose yourself is kept.
- **Kriko files a product under its catalog with your agent.** When a quick look
  is saved, Kriko matches it to an installed catalog by what it already knows. If
  that is not enough, the agent you picked reads the saved facts and the catalogs
  and proposes one, with the exact words it relied on. Kriko accepts it only when
  the catalog is installed, the confidence is high enough and the words are on the
  page. Otherwise the product stays uncategorized, and you can retry or choose.
  History keeps the method, the evidence and the catalog's version. An agent that
  works through MCP can list the catalogs and submit its own decision.
- **Optional: Jev from TypeSafe can do the filing instead.** Off by default. You
  turn it on in Settings, Research, and add a TypeSafe key in Keys. When Kriko
  cannot decide by itself, it sends the product title, the saved facts and the
  list of your installed catalogs to TypeSafe. It does not search the web. It is a
  paid service, and Kriko records the usage the service reports.

Also in this release: a benchmark for part compatibility (`python -m app.compatbench`),
which grades a model on five invented cases and checks every passage it cites.
It measures nothing until you run it against a model.

### 0.2.3

- **Kriko opens in a few seconds, not fifteen.** The engine was one file that
  unpacked itself into a temporary folder on every start, and on Windows that
  alone took 10 to 13 seconds. It is now a program with its files beside it,
  unpacked once by the installer. The shell also no longer waits for the search
  service before it starts the engine.
- **The window says it is starting.** Until the engine answers, the window shows
  the Kriko mark and "Starting Kriko…", not an empty page.
- **Kriko updates itself.** A few seconds after it opens, and every six hours
  after that, Kriko looks for a newer release. When there is one, a note offers
  Update now or Later. Update now downloads the installer, checks it against the
  checksums published with the release, closes Kriko, installs and opens it
  again. Your chats and catalogs stay where they are. Settings, About, shows the
  state and has a Check now button. A copy that was not set up by the installer
  (the portable zip) is pointed to the download page instead.

  This starts with 0.2.3: to get from 0.2.2 or earlier to this version, run the
  installer once by hand.
- **Chat finds the exact product and checks the seller.** A request such as
  "can you find these for me?" now searches the web. Before this change, a
  request in that form received an answer from memory, with no source. The
  answer now follows these rules:
  - Kriko reads the pages of popular and credible sites first. The list is the
    file `sellers.json`. Add your own sites in `~/.kriko/sellers.json`.
  - A code (a part number, a model number, an oil grade) is *confirmed* only when
    two trusted sites print it. The answer says so when it is not.
  - A marketplace is only as good as its seller. The answer names the seller and
    the score that the page shows, or it says the seller is unknown.
  - A page that calls itself official makes a claim. The answer reports it as
    the claim of the page.
  - The answer uses the language of your question.

- **The chat follows new text.** While an answer streams, the thread stays at
  the bottom. If you scroll up to read, it leaves you where you are.
- **Researches in the queue run side by side.** Every research waited on one
  shared draft claim, so the queue ran one at a time whatever the setting said.
  Several now run at once. Two researches on the same catalog still take turns,
  on purpose.
- **Learn this page works, and offers itself.** The panel offers Learn on a page
  of a shop Kriko does not know, including a real product page on an unknown
  shop. Once for each site, the browser extension suggests it when a page looks
  learnable.
- **Compare leads with the problems.** Each product shows its risks first, and
  its specifications in a table you can open.
- **A quick look is not its own source.** Specifications that only repeat the
  listing you gave are dropped, and the agent is told to check other shops.
- **"Original" in a title is not a check.** When you ask whether a seller or a
  part is genuine, the agent looks at the seller and at the maker's authorised
  dealers, and no longer counts the word in the product's title.

Also in this release, outside the installer: the website has been redesigned
around how Kriko finds the concern before you buy, and `kriko-mobile/` holds the
Kriko reader as an Expo app (run it in Expo Go).

### 0.2.2

- **Each answer shows which agent wrote it.** Claude Code, Codex, Antigravity,
  Mistral and the local model each have a mark of their own, above the answer
  and in the agent pick. An answer from an earlier version has no mark; Kriko
  never recorded who wrote it.
- **Copy, Retry, Edit.** Under an answer: Copy takes its words, and on the
  newest answer Retry asks the same question again. The newest question has an
  Edit button that puts it back in the box. Up in an empty box brings back what
  you asked before. A Latest button shows when you have scrolled away from the
  bottom of a long answer.
- **Rename, pin, search and copy a chat.** Each chat in the list has a
  "…" button. Rename (or double-click the name), Pin to keep it at the top, Copy
  as Markdown, Delete. The box above the list finds a chat by its name or by
  anything said in it.
- **Links in an answer open in your browser.** In the desktop window a link did
  nothing. Only web addresses (http and https) are opened.
- **No sample chats while Kriko starts.** For the seconds the app looks for its
  engine, the home screen and the lists showed demo rows, then swapped them for
  yours. They now wait.
- **The folded sidebar lines up.** The + for a new chat sat to the left of the
  other icons; the logo, the fold button, the + and the four pages share one
  centre line.

### 0.2.1

- **Learn this page.** The research card in the extension panel has a button
  that goes through the page you are on and learns what to take from it. It
  shows what it took and what each thing was taken as. The model on this
  computer answers at once. Another agent runs as a job the panel follows.
- **Pick the agent in the panel.** The research card lists the agents that
  are ready, starts on the one the app uses, and remembers your pick. It
  names the cost before you press anything.
- **A research search starts from the product, not the page title.** A title
  such as "Samsung Galaxy A54 256 GB Beyaz Fiyatları, Özellikleri ve
  Yorumları | En Ucuzu Akakçe" was searched whole, so the searches found the
  shop and its ranking words instead of the phone. The shop name and the
  words a shop adds to rank are taken off before any search is made.
- **A page about your phone is read, even if it never names the colour.** A
  review of the Galaxy A54 was thrown away because it did not repeat the 256 GB
  and the colour a listing's title adds. A model code such as A54 with another
  word of the name is enough to read the page. Each finding still has to show
  it applies.
- **The model on this computer maps a page correctly.** It took a pack's name
  for a key, and what it wrote was refused. It is given the key names alone.
- **Agents no longer fail with "does not declare per-run model selection".**
  Kriko asks each agent's program which flags it has. One slow first answer
  was remembered until you closed the app, so Claude Code and Antigravity were
  refused for flags they have. An empty answer is now asked again after a short
  pause.
- **Chat no longer ends on "SEARCH: …".** When an agent asked for a search in
  more than 14 words, the request was shown as the answer and nothing was
  searched. It is shortened and the search runs.

### 0.2.0

- **The desktop app is new.** It is built on Tauri now, with a blue look, a
  dither sky, and a dark and a light theme. Motion has three levels: Calm,
  Standard and Vivid.
- **Chat keeps your chats.** Press New chat to start one. Recent chats are in
  the sidebar. Deleting a chat asks first.
- **A tour on the first start.** It shows the box where you ask, the agent
  pick, where Kriko looks, and the places in the sidebar. Take it again from
  Settings.
- **The extension panel has the same look and its own tour.** It shows once,
  on the first product page. The options page can show it again.
- **Local models.** The Local model panel shows your graphics memory and the
  models Ollama holds. You can browse Hugging Face for GGUF models with
  filters for size, licence and sort order. A filter can keep only the models
  that fit your graphics card. A download starts only when you press Get.
- **vLLM on CUDA 13.** Kriko reads the CUDA version of your driver and shows
  the steps for the right build. It does not install anything. On Windows the
  steps use WSL 2. Kriko finds the server when it runs.
- **Catalogs and Sites panels.** Remove asks before it removes.
- **The sidebar, Compare and Queue** use the new layout. The installer is
  built from `kriko-ui/package.ps1`.

### 0.1.2

- **Chat answers are formatted.** An answer from an agent is markdown. A bold
  term is bold. A bullet list is a list. A table is a table. A link opens the
  page it names. Before this release the screen drew the characters: every
  asterisk, pipe and bracket reached the reader as itself.
- **You can select and copy an answer.** Drag over the words. Press Ctrl+C. The
  selection crosses a bullet and the paragraph under it, because the
  transcript holds one selection rather than one for each block.
- **One status line while an agent works.** The running turn showed a moving
  mark, a phase word and a second status line at the same time. The mark and
  one line remain.
- **A product card under an answer.** When a turn reads your catalogs, the
  answer now carries a card for each product it found. The card shows the name
  the catalog uses, the identity it is recorded under, and the number of
  recorded risks. **Open** reads the product in Browse. **Add to Compare** puts
  it beside the others and saves its check. **Read again** reads the product
  now, because an answer is a reading of the catalog at the moment it was
  written.
- **A calmer sidebar.** The rows have one rhythm. The fold control moved to the
  brand row, where it reads as this rail's control. A real edge separates the
  rail from the page; a hairline disappeared on a bright screen.
- **The model store is a list.** One full-width row for each model, with one
  primary action at the right edge. The name is the largest thing in the row.
  A size picker appears only on a model that is not installed and offers more
  than one size.
- **The local model lives with the agents.** **Agents** now shows a marketplace
  of every way to answer a question: the coding agents on this machine, the
  local model, and the paid APIs you hold a key for. Each row says what it is,
  where Kriko found it, and its state. It offers one action. The local model
  panel shows the model, the server and the number of models on the machine.
  **Local LLM** left the rail and keeps its own screen, which Agents opens.
- **The light theme is correct.** The hero band kept its dark image but its
  background followed the theme, so on the white ground it became a pale smear
  with light words on it. The band keeps its own colours in both themes. A new
  `EDGE` token separates two surfaces, where a hairline is only right for a
  rule inside one surface.
- **The browser extension is ready for the Web Store.** Version 0.4.2. Escape
  now closes the panel. One loading indicator replaces two spinners and a
  skeleton. The endless sky movement is one pass. A pack's tone value is
  escaped. The result cache is keyed by a digest, so the reader's own listing
  addresses are no longer written to disk as keys. The options page keeps a
  visible focus ring, and it no longer claims that nothing leaves the computer.
- **The agents are faster and they need less of the internet.** The plane
  decision took 1114 ms on a cold start and now takes 264 ms; the second and
  third question in one turn take 1.8 ms. One request on the loopback address
  took 17.19 ms and now takes 1.43 ms. A read of the installed catalogs used
  159 statements and now uses 6. Three of the four coding agents declare no
  page reader, so no internet server can attach to them. The rule that a paid
  API runs only after you pick it is unchanged.
- **A follow-up question carries less and knows more.** The brief for a saved
  check fell from 37,229 characters to 8,752. It still carries the product, how
  far it has been used, and every recorded risk with its page.
- **Kriko can work out how to read a new site.** When no installed catalog can
  read a page, the local model is asked to map the page's own labels. The
  result is checked before it is stored, and it is cached by the page's shape
  rather than by its address, so one inference serves every listing on that
  site. Nothing is recorded when no model is ready, and the reader can turn an
  inferred site off.
- Known limits: the desktop screens were compiled, unit-tested and observed in
  a window on Windows only. The agent speed figures come from one machine and
  exclude the model's own inference time. Nothing was checked on macOS. The
  browser extension is not yet published to the Web Store.
