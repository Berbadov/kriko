# Changelog

Reader-visible changes for each release. Newest first. Published versions are
immutable; a correction is a newer version.

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
