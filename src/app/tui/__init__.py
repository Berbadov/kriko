"""`kriko tui` — the operator's console for agent operations.

A fourth interface beside `cli`, `web` and `mcp`, and the only one whose
audience is not the reader of a car listing. It drives the same HTTP API the
dashboard drives, from a terminal, with no webview anywhere in the path — which
is what makes it usable in exactly the conditions that produced B107/B109,
where the desktop shell's window was the thing that did not work.

    kriko tui                 # attach to a running app, or start an engine
    kriko tui --url http://127.0.0.1:8787
    kriko tui --no-start      # attach only; fail if nothing is serving

See `app.py` for the loop, `screen.py` for the frame (pure), `term.py` for the
terminal, and `client.py` for engine discovery.
"""

from app.tui.app import main

__all__ = ["main"]
