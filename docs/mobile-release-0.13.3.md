Kriko Mobile 0.13.3 (17)

Chat input is restored on Home. A simple in-flow footer replaces the clipped floating bar.
Source language and answer language can be chosen independently in Settings (English/Turkish, or Any/Auto).
Screen reading uses a sweeping ribbon with moving contours and capture brackets.

Hover loading: assistant-only screen reads now retain the React Native headless runtime, including recovery from stale task IDs. Sharing status no longer stops assistant work. Android search/vision HTTP requests have native timeouts, and stream completion handles a bare DONE marker.

Validation: typecheck, lint and offline regression suite passed. Android release build, APK signature and 16KB zip alignment passed. Version 0.13.3 / 17, target SDK 36. This is a debug-certificate-signed test APK, not a Play publishing artifact.
The installed Home/footer and ribbon effect were visually inspected. The emulator disconnected during live research, so a completed live hover answer was not confirmed.
Automatic approval blocked changing the emulator default assistant with reason "blocked by policy". The exact power-button end-to-end flow still requires phone verification.

Install over the prior test build to retain history. Screenshots show the actual installed build.
