Kriko Mobile 0.15.0 (19)

The conversation now carries the reader's own history. A slim row of past-search
chips sits above the composer (up to three remembered products, each with a
coloured kind tile and its age); tapping one fills the composer without sending,
and "See all" opens the full remembered-search sheet with product, question,
time and source count. When the agent compares models or specifications it may
now write a Markdown pipe table; `src/engine/markdownTable.ts` parses it and the
answer renders a real table — raised header row, aligned columns, inline
bold/code/citations inside cells, hairline rows, and a sideways scroll with a
"swipe sideways" cue only when it is wider than the phone. A `---` line stays a
hairline rule, never a table delimiter outside one.

The screen-reading scan is now a liquid crest: metaball swells, deterministic
rising droplets and a fine LED-dot trail cross the page while the scan reads,
with the capture brackets kept. The floating answer sheet is a window the
reader owns: the header drags it anywhere, a 44 dp corner grip resizes it
(260x240 dp minimum, display-16 dp maximum, body scroll reflowing), and the top
indicator — grabber, chevron, "Swipe down to close" and a progress line that
fills as you pull — closes it on a long pull or a fast flick while a short pull
springs back. The same indicator, with the same gesture, is on every in-app
sheet. The sheet's loading bar is an LED dot matrix, the K carries a chasing LED
ring while it scans, and the in-app surfaces use one dot-matrix vocabulary:
live research shows a scan LED and a small K glyph, the screen-read sheets use
LED and liquid rows, and a faint 63-dot LED drift field with four slow liquid
patches animates behind the chat (never above 0.10 opacity, paused off-screen,
still under reduced motion). The colourful tile accents on past-search rows are
the reference build's playful cue, kept on the dark palette.

Validation: `npx tsc --noEmit`, `npx expo lint --no-cache` and
`npm run test:offline` pass (all 27 suites, including the new Markdown table
checks and 385-string i18n coverage). The Android release build succeeded; the
APK signature (debug certificate, V2) and 16 KB zip alignment were verified.
Version 0.15.0 / versionCode 19, target SDK 36. Installed over 0.14.0 with
history retained and observed on the kriko_pixel emulator (Android 16, API 36):
past-search chips and the full sheet, a live table answer with sideways
scrolling, the chat LED background, the live LED research state, the in-app
sheet swipe-down close (and a short-pull spring-back), and the native overlay's
liquid scan, drag, corner resize, swipe-down close, LED loading bar and K rim.
Screenshots are in docs/screens/0.15/; the scan animation was captured with
screenrecord and frames.

This is a debug-certificate-signed friends-test APK, not a Play publishing
artifact. Known limits: the floating sheet's resize floor is 260x240 dp (a very
large font scale can leave little body height, the scroll takes it); Android
content blur still needs API 31+ and a BlurTargetView; sheets in RN Modals
cannot blur the page underneath, so their backdrop is a veil; the new
animations are all transform/opacity on the compositor and pause when the app or
screen is not in front, and reduced motion turns them into still patterns.
