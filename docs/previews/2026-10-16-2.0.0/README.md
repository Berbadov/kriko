# Kriko 2.0.0 desktop review

> **A working note, not a release page.** It is dated 2026-10-16 and it uses the
> version numbering of that day: the tree was reset to `0.x` afterwards, so the
> release this work shipped in is **0.2.0** in `CHANGELOG.md`. The test figures
> below are the counts of that date, not of this tree. Nothing links here and
> `tools/bump.py` does not touch this folder, which is why it is worth saying:
> the numbers below go stale on their own.

Request: “make design more sleek. not populated. and improve every page. lets ditch box content design. improve animations and then get a good local agent selection section”. The supplied Atomic Chat screenshots informed the list/detail layout and restrained controls. The user also asked to remove the sky and title banners and reported a laggy Live button.

Done when: all desktop pages use the quieter layout, the model selector supports discovery and installed models, extension setup connects to agent selection, Live opens without animating column widths, and the main navigation and controls remain usable at 1280×860 and the supported 940×640 minimum.

## Changes

- Corrected the embedded font family names; Windows had been falling back to Segoe UI.
- Removed the sky/title banners, content-card fills, idle working rail, and glowing segmented meters. Shared sections use spacing and hairlines. Outline icons and ordinary numbers replace pixel controls.
- Simplified Home, made History analytics optional, and moved agent research options, Firefox setup, connection details, and local runtime controls behind explicit actions.
- Added a model list/detail workspace with Downloaded/Discover views, search, size selection, installed-model detection, download status/cancellation, runtime setup, and an extension handoff that saves the local-agent preference.
- Removed Live/sidebar width animations and construction of closed Live contents. Ready/Connected badges are static. Page and record fades last 140 ms and respect Reduce motion.
- Fixed stretched single-line inputs, broken sidebar product links, duplicated comparison counts, and RGB/RGBA severity colors. History citations and original listing URLs now open their stored web addresses.
- Removed Compare's lowest-risk-count summary; the evidence table and coverage gaps remain available.

## Windows observations

All 15 navigation pages were inspected in a native Windows preview: Chat, Home, New check, History, Compare, Overview, Browse, Sites, Agents, Local models, Activity, Benchmarks, Browser extension, Settings, and About. The fixture uses synthetic products/models; no paid research, real download, installation, key change, or deletion was submitted.

Observed interactions included keyboard product search, opening a non-newest saved check from Home, opening the exact sidebar product, discovering models, selecting an installed size, expanding the sidebar, opening About from the version footer, scrolling to model controls in a short window, and opening/closing Live at the minimum size. The Live observation confirms the new interaction and layout; it is not a measured latency benchmark.

Screenshots:

- [Local model workspace](local-models.png), [minimum-size model workspace](local-models-940.png)
- [Chat](chat.png), [minimum-size Chat](chat-940.png)
- [Home](home.png), [product details](browse.png)
- [Agents](agents.png), [browser-extension setup](extension.png)
- [Live at 940×640](live-940.png)

The expanded desktop fixture is reproducible with `python packaging/buyer_fixture.py <new-scratch-directory> --desktop-review`. It writes only to that scratch directory and blocks provider/research submissions.

## Validation and release limits

The full local gate passed: 3,130 Python tests, 19 skipped; 269 extension tests; 135 Rust tests; version agreement, Ruff, all mypy groups, and clean-wheel import/CLI smoke. Further final UI checks and packaging results are recorded in the release PR.

These screenshots establish Windows layout and the interactions listed above. They do not establish model quality, a successful real model download, every active-job state, macOS behavior, or installed-package behavior. The release remains a candidate until native packaging/smoke checks and source review are complete; no published assets were replaced.
