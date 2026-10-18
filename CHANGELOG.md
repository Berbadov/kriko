# Changelog

Reader-visible changes for each release. Newest first. Published versions are
immutable; a correction is a newer version.

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
