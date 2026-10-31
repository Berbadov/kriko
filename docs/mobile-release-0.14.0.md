Kriko Mobile 0.14.0 (18)

The agent now remembers what this phone researched. A small catalog is derived
from the conversation threads and the scan queue (one row per product, newest
first, capped at eight rows and 1,600 characters of prompt text), and every turn
carries it plus each prior user message's product identity. A follow-up such as
"the previous one" or "this one" resolves to a named product, and two products
are never merged; History shows the same rows as "Products Kriko remembers".
tools/test-memory.ts proves the split with fixtures (a drill and a laptop stay two
rows, a rescan replaces its row, pending turns are skipped, the brief names
both). A live turn on the emulator listed the phone's earlier products and
separated the two Toyota Prius researches from a non-product screenshot.

Settings is now a compact grouped list in the reference schema: section captions
over rounded cards, rows of accent icon tile + label + current value + chevron,
inline switches, and one checkbox sheet per row that carries the sentence the
old screen put under the label. Sources language is "Any" plus the desktop's 14
languages and Answers language is "Auto" plus the same 14, chosen independently;
the interface itself stays English/Türkçe. Price tracking stays inline because
its due-check effect is what runs when Settings opens.

The chat got one spacing scale and one type rhythm: 40px composer controls
(scan, image, mic, send), a glass composer deck and an opacity-only focus ring;
readable answer body at full ink contrast, a 12.5px answer footer with 44px
targets, and a rebuilt source section (22px numbered tile, two-line 15.5px
title, 12px mono host, 52px rows, one in-place expander plus the separate "All"
press that opens the Sources page). A `---` line in an answer is now a quiet
hairline instead of literal text.

Motion and glass: one spring vocabulary (press / morph / sheet / reveal), a
shared glass material (GlassCard / GlassBar) over expo-blur with the palette
glass fill as its fallback, a translucent top bar over scrolling pages with one
BlurTargetView per page, spring bottom sheets with a veil, measured disclosures,
and a single native fade transition. Android renders a real blur only on API 31+
and only where a BlurTargetView exists; elsewhere the palette fill is used.
Reduced motion removes all of it.

Validation: `npx tsc --noEmit`, `npx expo lint --no-cache` and
`npm run test:offline` pass (all 24 suites, including the 14-language checks,
phone-catalog memory and 374-string i18n coverage). The Android release build
succeeded; the APK signature (debug certificate, V2) and 16 KB zip alignment were
verified. Version 0.14.0 / versionCode 18, target SDK 36. Installed over 0.13.3
with history retained and observed on the kriko_pixel emulator (Android 16, API
36): settings top and scrolled sections, the language sheet with all 14
languages, a language choice applied and reset, a chat answer with its sources,
History's remembered products, the White palette, the version footer, and one
live memory turn. Screenshots are in docs/screens/0.14/.

This is a debug-certificate-signed friends-test APK, not a Play publishing
artifact. Known limits: Android content blur needs API 31+ and a BlurTargetView
(page top bar; inline glass otherwise falls back to the fill); a sheet in an RN
Modal is a separate native window and cannot blur the page underneath, so its
backdrop is a veil; the live memory turn spends provider keys.
