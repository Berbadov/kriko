Use one agent tile beside every agent name: in the running-agents rail, the agents table and the compare, benchmark and activity views. The tile is a 40px `well` with a 1px `hairline` ring and `radius-md`; the agent's own icon sits at 24px in the centre.

The icon must be the vendor's official file, taken from their brand or press kit, unmodified, in the single-ink or light-on-dark version their guidelines give for dark grounds. Keep one file per agent in `assets/Agents/` (`claude-code.svg`, `opencode.svg`, `antigravity.svg`, `mistral-vibe.svg`, `github-copilot.svg`, `claude-desktop.svg`, `cursor.svg`) and reference it with `<img>`; never redraw, recolour or approximate a vendor mark, and never invent one for an agent that has none.

Until an official file is supplied the tile shows a 5x5 LED monogram of the agent's first letter in `brand-bright`. Letters are drawn on the same grid as the LedMatrix glyphs (`A`, `C`, `D`, `H`, `K`, `M`, `O`, `P`, `R`, `U`). Internal agents that are not a vendor product (PipelineAgent, KnowledgeBot, ResearchBot) keep the monogram permanently.

The consumer provides the agent name and either the icon file or a letter. Pair the tile with the agent name in `body-strong`; the icon alone never identifies the agent.
