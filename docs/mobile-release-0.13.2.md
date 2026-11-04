# Kriko Agent 0.13.2 — floating answers and simpler navigation

31 October 2026 · package app.kriko.mobile · version code 16.

[APK](../kriko-mobile/dist/apk/kriko-agent-0.13.2.apk) ·
[Checksum](../kriko-mobile/dist/apk/kriko-agent-0.13.2.apk.sha256)

Size: 60,841,361 bytes. SHA-256:
`7b8d342f002022a3e37b81a2165d773b1faaed887c964295869ddf8d7f2b0523`.

## Changes

- Home has the floating navigation dock; chat has only the composer. The +
  button opens a dedicated chat, and Back returns home. Keyboard-visible chat
  also keeps navigation hidden, with safe-area spacing around the composer.
- Removed the oversized blue selection shape. Selection uses the icon and
  label, without a moving colored background. Removed “closer look” branding,
  reduced home copy and replaced the large trial warning with a compact row
  shown when entering chat.
- Added listening bars, a compact research animation and short phase labels.
  Sources show title/domain rows with two initially visible and an expand action.
  Raw research steps remain available behind a disclosure. Token diagnostics
  remain off by default.
- Added a replayable first-use guide with animated scan, voice and source
  demonstrations. Completion/skip is saved locally. Motion respects reduced
  motion and pauses in the background.
- Fixed an SSE transport bug: the server's terminal marker now completes the
  response immediately, including a marker without a final newline, instead
  of waiting for the HTTP socket to close. Added a deadline fallback, transport
  cleanup, cancellation checks and propagation of final-frame errors.
- Fixed native source-refresh tracking, selection of newly active scans and
  a stale-job recovery message. Streaming updates reuse the answer view rather
  than rebuilding the whole sheet for every text chunk.

## Verification

Typecheck, Expo lint, offline regressions and the Android release build pass.
The new stream tests cover fragmented frames, terminal-marker completion while
the socket stays open, final-frame errors, cancellation and missing timeout
callbacks. Native Kotlin compilation and Android release lint pass.

The release APK was installed over the existing emulator app without clearing
its data. Checked the three guide steps and completion persistence, home with
navigation only, + opening chat, chat with the keyboard open and no dock, and
Back returning home. Emulator keyboard/motion settings were restored afterward.
The emulator had startup problems in Android system processes; these were
separate from the observed app UI flow.

Signature v2 and 16 KB zip alignment pass. All 50 packaged native libraries have
ELF load-segment alignment of at least 16 KB. The 4,430,856-byte standalone
Hermes bundle and its source map match the reviewed source. This remains a
direct-install test APK using the project debug signing certificate.

The exact product-page/power-button failure still needs a retry on the physical
phone: no physical phone was connected, and the emulator's existing trial was
exhausted. No new paid research query or microphone recording was performed.
The transport regression is reproduced and fixed in deterministic tests; that
does not establish that every device-specific background failure is resolved.
