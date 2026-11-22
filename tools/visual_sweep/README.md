# Visual sweep

Drives the real desktop UI and fails on what the unit suites cannot see: a title
that fell back to a serif, a menu that runs off the window, two sets of window
buttons, a page that scrolls sideways, a cut-off choice list, a console error.
A full run is about two minutes; `--quick` is about forty seconds.

```
# the packaged window (preferred)
$env:KRIKO_VERIFY = "1"                      # do not fold into a Kriko that is open
$env:KRIKO_STORE = "C:\scratch\store.db"     # a scratch profile, files not folders
$env:KRIKO_APP_STATE = "C:\scratch\state.db"
$env:WEBVIEW2_USER_DATA_FOLDER = "C:\scratch\wv2"
$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = "--remote-debugging-port=9222"
.\kriko.exe
node tools/visual_sweep/sweep.mjs --cdp http://127.0.0.1:9222 --out <folder>

# the built UI in a browser, with an engine behind it (no window buttons expected)
node tools/visual_sweep/sweep.mjs --url http://localhost:5173 --out <folder>
```

Options: `--quick`, `--ask "question"` (a real answer and a follow-up, needs a ready
agent and spends the reader's own allowance), `--reconnect <engine pid>` (kills the
engine, expects the offline screen, presses Reconnect and expects the window back;
add `--only-reconnect` to skip the walk and do just that). `--only-ask` skips the
walk and does just the question and its follow-up.

It needs Playwright, found in this checkout or the global npm folder. Screenshots
and `sweep-results.json` go to `--out`; the exit code is 1 when a check fails.
