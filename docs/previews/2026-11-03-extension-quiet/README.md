# The extension, quiet

The reader asked: "remove subtext and expressive logs from the web extension".

Each pair below shows the same state before and after. The "before" pictures
come from `origin/main`. The "after" pictures come from this branch. Both use
the extension's own panel page (`extension/tests/preview/panel.html`) and its
options page, with the engine answers stubbed. Nothing here ran against a real
engine or on Windows.

| State | Before | After |
|---|---|---|
| A run in flight, task log open | `run-before.png` | `run-after.png` |
| A run that failed | `failed-before.png` | `failed-after.png` |
| A quick look that found risks | `found-before.png` | `found-after.png` |
| A site no catalog reads | `no-catalog-before.png` | `no-catalog-after.png` |
| The engine is not running | `error-before.png` | `error-after.png` |
| The options page | `options-before.png` | `options-after.png` |

## What changed on screen

- A run shows its stage and its true counts ("Step 4 of 4", "source 2 of 4",
  "4 of 5 pages read"). The Task log is gone, so no raw line of the run
  reaches the panel. "Open in Kriko" opens the full job in the app, and that is
  the only way to read the log.
- The options page lost every description line under its headings, and the
  "If nothing answers" section.
- A verdict card is its word and its buttons. The explaining sentence stays
  only for a "probably" verdict, which is a question the reader must answer.
- The error picture differs only because the preview page now carries the
  worker's shorter wording. The panel shows whatever the worker says.
- No picture shows the tour, the tooltips or the "No data yet" card. Tests
  cover those.

## What did not change

- The cost line ("Free · on this computer"). It states whether a press costs
  money.
- The relay line in the watch form ("The page goes to your relay"). It states
  that data leaves the machine.
- Error states and their action ("Kriko is not running. Start the app.").
- The "What was compared" view. It opens only when the reader presses it.
