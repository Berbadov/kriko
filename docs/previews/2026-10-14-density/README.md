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
