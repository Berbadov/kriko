# Bundled webfonts

One family, IBM Plex Mono, under the SIL Open Font License 1.1, checked in
rather than fetched at runtime. A desktop app cannot assume the network, and
`tokens.test.ts` fails the build on any `@import` or `fonts.googleapis`
reference for exactly that reason.

The whole app is set in it (B159). Plex Mono is not a variable font upstream,
so each weight and each slope is a file of its own, and the app sets exactly
these. Anything else the browser would have to fake.

| Weight | Upright | Italic | Used for |
|--------|---------|--------|----------|
| 400 | `ibm-plex-mono-latin-400.woff2` + `-latin-ext-400` | `-latin-400-italic` + `-latin-ext-400-italic` | text; italic marks anything different or important |
| 500 | `ibm-plex-mono-latin-500.woff2` + `-latin-ext-500` | | buttons and other controls |
| 600 | `ibm-plex-mono-latin-600.woff2` + `-latin-ext-600` | `-latin-600-italic` + `-latin-ext-600-italic` | headings and bold |

Each weight ships **latin and latin-ext**, split by `unicode-range` so the
second file is only fetched when the page actually renders one of its glyphs.
The extension's market is TR/EU and `ş ğ ı İ ö ü ç` all live in latin-ext, so
a latin-only subset would have fallen back to a system face mid-word.

`fonts.css` falls back to a real monospace system stack, so a missing file
degrades to plain text rather than to nothing.

Source: the `@fontsource/ibm-plex-mono` 5.3.0 package (jsDelivr), which repackages
the upstream release at https://github.com/IBM/plex unchanged, latin and
latin-ext subsets only. Copyright 2017 IBM Corp., with Reserved Font Name
"Plex". Licence: https://openfontlicense.org

Until 2026-09-29 the app also carried IBM Plex Sans (the body face), Sora,
Silkscreen and JetBrains Mono. Sora, Silkscreen and JetBrains Mono belonged to
the Lemonade theme and Plex Sans to the Panel body; the theme choice and the
sans face are gone, and so are their files.
