# Kriko UI captures — 2026-10-12

These are real GPUI app-window screenshots at **940 × 640**, captured on
Linux/X11 with Xvfb and Mesa lavapipe. Each `before-*` image is the untouched
`HEAD` desktop binary; each `after-*` image is the current working-tree
binary. Both sets used the same current Python sidecar, temporary empty store,
window size, route, and host agent discovery. `KRIKO_VERIFY` selected a route;
it did not add or replace screen data. Empty history and drafts are the real
result of the isolated store. The Live view was opened with a pointer click on
its titlebar control.

| Screen | Before (`HEAD`) | After |
| --- | --- | --- |
| Home | [before-home.png](before-home.png) | [after-home.png](after-home.png) |
| Agents | [before-agents.png](before-agents.png) | [after-agents.png](after-agents.png) |
| Run | [before-run.png](before-run.png) | [after-run.png](after-run.png) |
| Local LLM | [before-local.png](before-local.png) | [after-local.png](after-local.png) |
| Home with Live open | [before-home-live.png](before-home-live.png) | [after-home-live.png](after-home-live.png) |

The before binary was built from commit `0fa66b101c07ed434a0ca036bad3810af64a545c`
using `git archive HEAD kriko-gpui` and the warmed Cargo cache. The after
binary was the existing `kriko-gpui/target/debug/kriko`; capture did not rebuild
or modify it. Both use GPUI 0.2.2, Python 3.13, and the same backend checkout.

The display used a private Xauthority cookie, a Unix socket, and
`Xvfb :96 -pn -nolisten tcp -auth "$AUTH" -noreset -screen 0 1600x1000x24 -dpi 96 -extension MIT-SHM`.
No TCP listener or unauthenticated X access was enabled. To keep the sidecar's
data writable without changing the host home directory, the capture environment
set `KRIKO_STORE`, `KRIKO_APP_STATE`, `KRIKO_ANALYSES_LOG`, `KRIKO_LOG`, and
`KRIKO_DIST` to paths under `/tmp/kriko-ui-preview-20261012`; `KRIKO_PACKS`
pointed at the checkout's real packs.

GPUI 0.2.2 on X11 can leave its initial map notification queued until another
input event. After each window mapped, the harness moved the pointer into the
window with `XWarpPointer`, waited for the frame, and captured the window with
ImageMagick `import -window <window-id>`. `after-home-live.png` and
`before-home-live.png` additionally clicked the real Live control with XTest.
This workaround changes no app code or screenshot pixels; the PNGs are direct
window captures.
