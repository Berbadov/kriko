# Bundled webfonts

Three families of the kriko design system, plus the app's previous face, all
under the SIL Open Font License 1.1, checked in rather than fetched at runtime.
A desktop app cannot assume the network, and `tokens.test.ts` fails the build
on any `@import` or `fonts.googleapis` reference for exactly that reason.

The design system (`kriko-svelte/`) sets its screens in three faces, and the
app now wears the same three: **Barlow Condensed** for display, **DM Sans**
for reading, **JetBrains Mono** for figures and labels. **IBM Plex Mono**
stays bundled as the mono stack's named fallback so nothing that asks for a
monospace face silently gets a proportional one.

Each weight ships **latin and latin-ext**, split by `unicode-range` so the
second file is only fetched when the page actually renders one of its glyphs.
The extension's market is TR/EU and `ş ğ ı İ ö ü ç` all live in latin-ext, so
a latin-only subset would have fallen back to a system face mid-word.

| Family | Weight | Files | Used for |
|--------|--------|-------|----------|
| Barlow Condensed | 600, 700 | `kriko/barlow-condensed-{600,700}-latin{,-ext}.woff2` | display: titles, keys, verdicts |
| DM Sans | 400, 600 | `kriko/dm-sans-{400,600}-latin{,-ext}.woff2` | reading: body, cells, inputs |
| JetBrains Mono | 400, 600 | `kriko/jetbrains-mono-{400,600}-latin{,-ext}.woff2` | figures, eyebrows, notes |
| IBM Plex Mono | 400, 500, 600 + italics | `ibm-plex-mono-*.woff2` | the mono fallback stack |

`fonts.css` falls back to real system faces of the same class, so a missing
file degrades to plain text rather than to nothing.

Sources: Google Fonts (Barlow Condensed by Scott & Trexler, DM Sans by
Colophon Foundry, JetBrains Mono by JetBrains, IBM Plex Mono by IBM Corp.),
all SIL Open Font License 1.1: https://openfontlicense.org
