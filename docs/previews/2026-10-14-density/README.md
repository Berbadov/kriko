# Density: desktop screens before and after

Captured under Xvfb with the software Vulkan driver (lavapipe), against an
isolated engine and store holding the `cars` pack. Window sizes are the
client area.

| File | Screen | Window |
|---|---|---|
| before-home-1280x800.png | Home, before the change | 1280x800 |
| before-overview-1280x800.png | Overview, before | 1280x800 |
| before-settings-1280x800.png | Settings, before | 1280x800 |
| after-home-940x640.png | Home, after (minimum window) | 940x640 |
| after-overview-1280x800.png | Overview, after | 1280x800 |
| after-run-1280x800.png | Run, after (idle) | 1280x800 |
| after-agents-940x640.png | Agents, after (minimum window; rail folded to icons) | 940x640 |

The "before" captures are from the branch base, before the coordinator's
merge. The "after" captures are from the merged build, so they also show the
coordinator's new cards (next-step card, pack install). Settings and the
940x640 Overview were not recaptured after the merge.

## Second pass: "the cards are too spacious"

The `tighter-*` captures are the same build setup after a second pass: card
inset 12 x 14 px (was 16), radius 12, section gap 12, card gap 8, row padding
6 px (was 10), empty-state wells 12 x 6, totals at 28 px, the next-step
callout 12 x 16, the Overview install and update offers side by side, and no
duplicate "Start a check" in Home's empty Drafts card. `settings` was captured
before the last two tweaks; the rest are from the final build.
