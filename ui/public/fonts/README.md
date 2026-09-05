# Bundled webfonts

Three families, all under the SIL Open Font License 1.1, checked in rather than
fetched at runtime. The extension's `colors_and_type.css` `@import`s these from
Google Fonts, which is fine for a page that already has the network — a desktop
app does not, and `tokens.test.ts` fails the build on any `@import` or
`fonts.googleapis` reference for exactly that reason.

| File | Family | Why |
|------|--------|-----|
| `sora.woff2` | Sora (variable, 100–800) | body. One file, not two: it is variable, so Google returns the same bytes for every weight asked for. |
| `silkscreen-400.woff2` | Silkscreen | the pixel display face — the lemonade theme's signature |
| `jetbrains-mono-400.woff2` | JetBrains Mono | code, identifiers, digests |

Latin subset only. Every family falls back to a real system stack in
`themes/*.css`, so a missing file degrades to plain text rather than to nothing.

Sources: fonts.google.com. Licence: https://openfontlicense.org
