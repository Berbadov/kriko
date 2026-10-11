# Native Windows release observations — 2026-10-11

Target: GPUI desktop, Python engine/API, and browser extension. The Svelte app and its static bundle are removed.

## Artifacts

- MSI: `kriko-1.3.0-x86_64.msi`, 47,869,952 bytes.
- MSI SHA256: `281120f513667e40de8365171d685726b999fa9a26459b84f99a02be41b09139`.
- Native application: 16,203,776 bytes; frozen engine: 32,128,277 bytes.
- Bundled OpenSERP is pinned by digest and accompanied by its MIT license. The Public Suffix List is included in the frozen engine and Python package.

The packaging recipe built the engine and GPUI application. WiX initially rejected per-user OpenSERP components with ICE38; their key paths were corrected to HKCU registry entries. The MSI was then relinked and the remaining smoke, portable archive, and checksum steps completed. This was a resumed recipe, not one uninterrupted successful `package.ps1` invocation. WiX emitted existing ICE63/ICE91 warnings.

## Installed application

The reviewed MSI was installed per-user with `msiexec` (exit 0). The installed GPUI executable was launched and spawned its installed engine and bundled OpenSERP.

- Engine health: version 1.3.0, healthy.
- Local plane: ready, `qwen3.5:4b`, context 4096, response language auto, search language en.
- OpenSERP health: healthy.
- Native focus API: accepted and delivered as raised.
- Extension API: staged, manifest version 0.4.1. Existing unpacked extensions require a browser reload to pick up updated files.
- Root HTTP endpoint identifies the GPUI/local API service rather than serving a removed frontend.

## Real local Quick Look

An installed-engine request for Sony WH-1000XM5 completed successfully in 79 seconds. Revision and market were explicitly unknown.

Observed coverage: four searches, 19 unique hits, five readable pages from five publisher buckets, three relevant pages and three completed evidence passes, one rejected candidate, two cited pages, no pipeline errors. One page was unreadable and two readable pages were excluded as unrelated or uncertain. One specification was quoted from iFixit; one hinge failure report was quoted from another publisher.

The hinge card has one supporting publisher, labeled `reported`. Reading several pages does not establish independent corroboration for every claim. This observation confirms installed search/read/extract/output integration; it does not verify the publishers' factual claims.

## Evidence and limitations

The controlled [model comparison](2026-10-11-local-pipeline.md) covers three installed models with identical fictional evidence. Qwen 4B at 4096 was the smallest tested configuration meeting those cases; it is not a general model ranking or a guarantee against hallucinations.

Static checks completed for changed Python modules, JavaScript syntax, Rust compilation, and whitespace. A second agent reviewed the pipeline and integration source after the identified fixes, with no additional critical issue reported. No pytest, Vitest, or other test suites were run.

Visual GPUI and browser-extension observations remain incomplete: the Windows computer-use helper pipe was unavailable after the prescribed retry/reset recovery. API responses and running processes are evidence of runtime behavior, not screenshots or proof of screen layout. The request entries remain open pending the reader's visual confirmation and source merge.

The existing v1.3.0 tag remains at its original source commit. The updated installer source is recorded by the release's linked review commit/PR.
