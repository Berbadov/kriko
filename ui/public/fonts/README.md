# Bundled webfonts

Five families, all under the SIL Open Font License 1.1, checked in rather than
fetched at runtime. A desktop app cannot assume the network, and
`tokens.test.ts` fails the build on any `@import` or `fonts.googleapis`
reference for exactly that reason.

| File | Family | Used by |
|------|--------|---------|
| `ibm-plex-sans-latin.woff2` + `-latin-ext` | IBM Plex Sans (variable, 400–600) | **panel** — body. The extension's face. |
| `ibm-plex-mono-latin.woff2` + `-latin-ext` | IBM Plex Mono 400 | **panel** — code, identifiers, digests |
| `sora.woff2` | Sora (variable, 100–800) | lemonade — body. One file, not two: it is variable, so Google returns the same bytes for every weight asked for. |
| `silkscreen-400.woff2` | Silkscreen | lemonade — the pixel display face |
| `jetbrains-mono-400.woff2` | JetBrains Mono | lemonade — mono |

IBM Plex ships **latin and latin-ext**, split by `unicode-range` so the second
file is only fetched when the page actually renders one of its glyphs. The
extension's market is TR/EU and `ş ğ ı İ ö ü ç` all live in latin-ext — a
latin-only subset would have fallen back to a system face mid-word. The two
lemonade families remain latin-only; that theme is not the default.

Every family falls back to a real system stack in `themes/*.css`, so a missing
file degrades to plain text rather than to nothing.

Sources: fonts.google.com. Licence: https://openfontlicense.org
