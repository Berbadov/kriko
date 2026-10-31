# Kriko Agent 0.13.0 — direct Android APK

Built 31 October 2026 from the mobile upgrades worktree, including the latest
merged main through `e99a9bf6`, the mobile polish branch and the new mobile/voice
changes. Version code: **14**. Package: `app.kriko.mobile`.

[APK](../kriko-mobile/dist/apk/kriko-agent-0.13.0.apk) ·
[SHA-256 sidecar](../kriko-mobile/dist/apk/kriko-agent-0.13.0.apk.sha256)

- File size: 60,805,177 bytes (about 58 MiB).
- SHA-256: `c774960173509334270960ad46f9703a56ff68ef5a56b530ec65827b23129ad1`.
- Architectures: `arm64-v8a`, `x86_64`.
- Minimum Android API: 24. Target Android API: 36.
- Signed using the same project debug keystore as the earlier friend build;
  APK Signature Scheme v2 verification passes. This is a direct-install test
  distribution, not a production-signed Play release.
- The already-configured local trial/shared-access bundle is preserved. Its
  trial and access code open successfully; an incorrect password is rejected.
  No provider keys or access passwords are recorded in these notes.

## Verification

- Gradle `:app:assembleRelease` succeeded, including R8, release lint and packaging.
- The APK contains a non-empty Hermes bytecode bundle, not a Metro-dependent
  debug loader. The earlier standalone-export temporary-file issue did not
  prevent this release build from producing Hermes bytecode.
- `apksigner verify --verbose --print-certs` passes.
- APK metadata reports version `0.13.0` / code `14`, the expected package,
  target SDK, architectures and microphone permission.
- `zipalign -c -P 16 4` passes. All **50** packaged native libraries have
  ELF load-segment alignment of at least 16 KB. This does not replace runtime
  testing on a 16 KB device.
- Typecheck, Expo lint, the offline suite and Android Kotlin compilation passed
  during implementation, including voice permission/cancellation regressions.

No Android phone was attached for installation or speech/capture interaction
testing. Install over the previous same-signed build to retain app data rather
than uninstalling first.

The [launch and pricing plan](mobile-launch-and-pricing-2026-10-31.md) identifies
the separate production work needed for Google Play and subscriptions.
