# The Kriko browser extension

The panel that reads the page you are on and shows what the installed catalogs
know about that product. Chromium (Chrome, Edge, Brave) loads the folder
directly; `python packaging/build_extension.py --output kriko-firefox.xpi`
stages the same source as a Firefox add-on.

## Where the knowledge comes from

1. **The desktop app**, when it is running. The worker asks
   `http://127.0.0.1:8787/api/analyze` and the app's own engine answers. This is
   the full answer: adapters, identity matching, ranking and the agent's
   research all live there. The panel's footer names the packs that answered.
2. **The offline catalogs**, when the app is not running and the reader has
   turned them on. The worker downloads the release's `packs.json`, then each
   `.kpack` it names, checks the file's `sha256` against the index before
   reading a byte, and stores what it read in the browser. The lookup runs
   here: the page's own title and labelled facts are matched against the
   catalog's identity values, and the claims behind the winning subject are
   drawn with their sources. The footer says **offline catalog** so an answer is
   never mistaken for a fresh one.
3. **Nothing else.** No provider key, no account and no Kriko server is stored
   in the extension or contacted by it. Research that needs a model still goes
   through the running app, which is the only thing that holds a key.

## Turning it on and updating it

Settings → **Offline catalogs**:

- the switch turns the fallback off and on; it is on by default, and the app is
  still asked first either way;
- **Update catalogs** reads the newest release index and installs any catalog
  whose version or `sha256` changed. The browser asks once for permission to
  read `github.com` and its asset host, because the index and the packs are
  cross-origin downloads; nothing else is requested;
- each catalog can be removed, and the page shows how much storage the
  extension uses.

The catalogs live in **IndexedDB**, one record per pack: a catalog is megabytes
of claim text and `storage.local` is a few. Only the small installed index
(version, digest, size) sits in `storage.local`. The service worker can be
stopped by the browser at any moment; the database is not, so there is no
startup timer and no "keep alive" trick.

## Limits worth stating

- The offline match is deliberately smaller than the engine's: it compares the
  catalog's identity values with the page and answers for the best subject. It
  does not re-rank, does not consult an agent, and a page it cannot place is
  "unknown", never an empty "no problems".
- A catalog is read with `offline/sqlite.js`, a read-only reader for SQLite's
  documented file format, because a `.kpack` is a SQLite database and a browser
  cannot open one. It refuses anything that is not SQLite and bounds every read
  to the file.
- The extension ships no catalog data. Like the desktop installer, it carries
  none: catalogs are installed from the release index, so a stale copy cannot
  be forgotten in the package.

## Tests

`bun run test` from the repository root runs every extension suite, including
`offline_catalog.test.js`, whose fixture is a real `.kpack` with an overflow
page, and the panel's own tests. The gate fails a run that reports zero tests.
