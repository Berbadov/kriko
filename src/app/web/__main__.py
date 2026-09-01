"""`python -m app.web` — the entry point app.py's docstring has always promised.

Without this file that command fails with "'app.web' is a package and cannot be
directly executed", and the working invocation is the less obvious
`python -m app.web.app`. Both the module docstring and the README document the
package form, so the package form is the one that should work.
"""

from app.web.app import main

raise SystemExit(main())
