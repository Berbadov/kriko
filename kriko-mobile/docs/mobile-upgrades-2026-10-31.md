# Mobile assistant improvements

Updated through `origin/main` at `e99a9bf6`, with the mobile assistant polish branch
through `97ea680b` merged first. Its notifications, updater, scan dock and
existing assistant UI are retained.

- Assistant route scans enter the research queue before navigation. Failed
  screenshot reads have a retry action. Native handoff and research watchdogs
  replace indefinite waiting with a visible failure.
- Product searches can attach clickable merchant-page image cards. Images and
  prices come from the actual result page's metadata; unavailable images use a
  placeholder. Compatibility research establishes the existing product and
  its requirements before finding candidates. Cards offer a merchant credibility
  research action.
- Settings persist product priorities, a target source count, and whether to
  include isolated reports and one-time issues. Source count is a research
  target subject to evidence and the existing time/tool budget.
- Gray has a separate charcoal palette in React Native and the Android overlay.
  Dark, Paper and White remain available. Queue answers use the full text width.
- Screen-read audit records are saved before vision uploads, including a small
  local screenshot, timestamp, outcome and observed product text. Failed reads
  remain inspectable. The Privacy page explains storage and provider/site
  requests and displays the recorded content. Clearing history clears audits.
- Provider-reported Mercury token usage is available through the optional usage
  setting. It starts off; counts are not estimated and do not include vision or
  search usage that those providers did not report.
- The existing BYOK flow keeps Mercury and DeepSeek keys in secure storage;
  price checks resolve credentials inside the store, rather than passing keys
  into UI components.
- Voice typing adds a 48-point microphone button beside the message field,
  visible listening/finishing states, stop and cancel controls, and editable
  partial/final transcription. Existing typed words are preserved, cancellation
  restores the original draft, and sending is disabled until dictation finishes.
  Microphone access is requested only after a tap. Android's recognition service
  handles speech (which may use its provider's servers); Kriko stores no audio.
  Turkish UI requests Turkish speech; otherwise the phone's default locale is
  used. Leaving the app stops recording. A recognition service must be installed.
- Price watches support editable 1/6/12/24/72/168-hour intervals, pause/resume,
  removal and manual checks. Prices require an unambiguous amount from the
  matching page. Failed checks keep the previous observation.

## Verification

Run `npm run typecheck`, `npm run lint -- --no-cache`, and
`npm run test:offline` from `kriko-mobile`. Offline regressions include assistant
queue cancellation, audit transaction ordering and clearing, product metadata
and redirects, price parsing and failed checks, theme contrast, translations,
and the existing capture/queue/history/update tests.
Voice checks also cover partial hypothesis replacement, late callbacks,
permission denial, cancellation during the permission dialog, and preserving
the typed draft.

Typecheck, Expo lint (without cache), the complete offline suite, web export,
and Android JavaScript export (`--no-bytecode`) passed in this session. Hermes
bytecode export could not create its temporary output file on Windows
(`permission denied`, exit 6), including when retried with a short temporary
path. This is separate from the passing JavaScript bundle check.
Android `:app:compileDebugKotlin` also passed, including the new voice typing
bridge and recognizer. The native check used the existing short-path Android
dependency layout documented in the mobile README. This verifies compilation,
not speech-service availability or recognition accuracy on a phone.

The subsequent standalone **0.13.0** release APK also built successfully with
Hermes bytecode. Signature, package/version, 16 KB ZIP alignment and all 50
native-library ELF alignments were verified. The existing trial/access setup
was restored for this friend build. See the [release record](../../docs/mobile-release-0.13.0.md).

For a credential-free local build, the ignored `src/engine/secrets.ts` can use
empty `PEPPER` and `TRIAL_BUNDLE` strings and `TRIAL_QUESTIONS = 0`. That build
offers BYOK without baked trial/shared access. Use the project's normal secret
generation process for a trial-enabled distribution; do not commit keys.

## Remaining verification and limitations

- Power-button entry, overlays, scrolling and swipe feel need an Android phone
  check. Offline tests and compilation do not establish device behavior.
- Price scheduling runs while the Settings price-tracking surface is mounted
  and the app is active, with due checks on return and once a minute. It does
  not run in the background or issue background price-drop notifications.
- Merchant sites can block metadata or images; such results retain their real
  listing links and a placeholder. A listed price is an observation, not a
  checkout guarantee.
- Only the existing Mercury/DeepSeek provider pair is supported for BYOK.
