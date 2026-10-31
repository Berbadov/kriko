# Kriko Agent 0.13.1 — optional Mistral routing

Built 31 October 2026 from the mobile upgrades worktree, based on merged main
through `b5cc2ee7`. Package `app.kriko.mobile`, version code **15**.

[APK](../kriko-mobile/dist/apk/kriko-agent-0.13.1.apk) ·
[SHA-256](../kriko-mobile/dist/apk/kriko-agent-0.13.1.apk.sha256)

- Size: **60,826,077 bytes**.
- SHA-256: `aa97679074637c3a42624f58e072b3988934c8456cadb5f72f0b42b94cd85a77`.
- Adds an optional Mistral key to BYOK, stored in SecureStore. Existing two-key
  grants still work. The machine environment key was used for benchmarking;
  it was not embedded in the APK. The existing trial bundle is preserved.
- Eligible translations, Turkish rewrites and basic explanations use Ministral
  8B; eligible English rewrites and approved basic definitions can use 3B.
  No 14B route. GLM Flash is benchmarked, not enabled as an app route.
- Product research, screen context, history-dependent requests and non-default
  research preferences retain Mercury. Failed or uncertain quick responses
  fall back to research within the shared turn deadline.
- Static answers can be reused from credential-scoped process memory for ten
  minutes, at most 32 entries. History/access clearing invalidates the cache,
  including pending writes. No fresh price or merchant cache is introduced.

## Verification

- Typecheck, Expo lint and offline regression suite pass.
- Gradle release build succeeds, including Android release lint and R8.
- Signature v2 verifies and its signing certificate matches 0.13.0. This remains
  a direct-install test APK using the project debug certificate.
- APK metadata confirms version 0.13.1 / code 15, minimum SDK 24, target SDK 36,
  ARM64 and x86_64, and microphone permission.
- The standalone Hermes bundle is 4,415,572 bytes and contains both pinned
  Ministral IDs. It does not require Metro.
- APK 16 KB zip alignment passes. All 50 native ELF libraries have load-segment
  alignment of at least 16 KB. No phone interaction test was performed.

See the [updated pricing plan](mobile-launch-and-pricing-2026-10-31.md) and
[synthetic benchmark](../benchmarks/ministral-synthetic-2026-10-31.md).
