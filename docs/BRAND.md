# Use the mark

Everything shown (toolbar tile, taskbar icon, favicon, rail) is generated. Change a source, re-render, commit output:

```bash
python packaging/render_icon.py
python packaging/render_lockup.py
```

**Two sources, only two.** Everything else is output:

```mermaid
%%{init: {"theme":"base","themeVariables":{"fontFamily":"ui-monospace, SFMono-Regular, Consolas, monospace","primaryColor":"#090E1B","primaryTextColor":"#F2F5FF","primaryBorderColor":"#1F4FFF","lineColor":"#86A3FF","secondaryColor":"#1739C2","tertiaryColor":"#080B16","noteBkgColor":"#BFE4FF","noteTextColor":"#05070F","actorBkg":"#090E1B","actorTextColor":"#F2F5FF","actorBorder":"#1F4FFF","signalColor":"#86A3FF","signalTextColor":"#86A3FF"}}}%%
flowchart LR
    S1["logo-mark.svg<br/>(16x16)"]:::brand
    S2["logo-mark-large.svg<br/>(64x64)"]:::brand
    S1 --> O1["extension/assets/icons/<br/>icon-{16,32,48,128}.png"]:::ice
    S1 --> O2["ui/public/mark.svg"]:::ice
    S2 --> O3["packaging/icon-master.png<br/>(1024px)"]:::ice
    S2 --> O4["ui/public/mark-large.svg"]:::ice
    S1 -->|"+ KRIKO"| O5["extension/assets/logo-lockup.svg"]:::ice
    S1 -->|"+ KRIKO"| O6["extension/assets/logo-lockup-mono.svg"]:::ice

    classDef brand  fill:#1F4FFF,stroke:#86A3FF,color:#F2F5FF
    classDef ice    fill:#BFE4FF,stroke:#1F4FFF,color:#05070F
```

> **Tests fail and you did not touch the mark?** Somebody edited an output. Re-run both scripts and commit. If a test still fails, a source was edited without re-rendering.

## Which file to reach for

| You want | Use | Source? |
|---|---|---|
| Toolbar icon | `extension/assets/icons/icon-*.png` | rendered |
| Favicon | `ui/public/mark.svg` | rendered |
| Rail (32px, smooth) | `ui/public/mark-large.svg` | rendered |
| App icon master | `packaging/icon-master.png` | rendered |
| Logo with name | `extension/assets/logo-lockup.svg` | rendered |
| Logo on foreign ground | `extension/assets/logo-lockup-mono.svg` (`currentColor`, no ground) | rendered |
| Change mark ≤48px | `extension/assets/logo-mark.svg` | **source** |
| Change mark ≥128px | `extension/assets/logo-mark-large.svg` | **source** |

## The three colours

Owned by `ui/src/styles/themes/panel.css`, borrowed by the mark — so it never sits on the rail as a foreign object. A test asserts mark hex and theme tokens agree.

The desktop app's own palette lives in `kriko-gpui/src/theme.rs`. Diagrams in these documents use it; see [how the docs are written](STYLE.md).

| Role | Token | Value |
|---|---|---|
| Ground | `--n-2` | `#15171C` |
| Letter | `--n-9` | `#E7E9ED` |
| Rising arm | `--accent` | `#E8C04B` |

## Two marks, one design

Nearest-neighbour is the only scale that keeps pixel art intact — so the 16×16 grid became eight hard blocks at 1024px ("pixelated and very ugly", correctly). The mark is therefore drawn twice; same letter, colours, and slab-stem-with-rising-arm idea, differing only in what each size can carry (a true diagonal is blur below 48px; a stepped one is a mistake above 128px).

| Size | Source | Rasterisation |
|---|---|---|
| 16–128px: toolbar, favicon | `logo-mark.svg` | integer nearest-neighbour, exactly three colours |
| 1024px master: installer, taskbar, rail | `logo-mark-large.svg` | scanline fill, 4× supersampled, real diagonals |

Large-mark vocabulary is `rect`/`polygon` only — `render_icon.py` ships its own rasteriser and a `path` would need a bezier flattener in a build script. Tested, not trusted: the colour test fails on a hex moved in one mark only; `test_the_app_icon_is_actually_antialiased` counts master colours (three = somebody pointed it at the grid).

## The grid

Small mark: 16×16 grid of rects, cap height 14 cells, 3-cell stroke; wordmark drawn on the same grid (no font file, no network, no drift with the display face). Clear space one stroke (3 cells) all round; 10 cells between mark and word — at a normal gap the eye reads "KKRIKO".

## Why it looks like this

A slab K; the upper arm is the accent. Mass survives 16px where hairlines smudge; the whole arm (not one terminal block, which reads as a detached square below 48px) rises like a step chart — the product in a glyph, in the panel's existing warning colour.

## Next

- [How the docs are written](STYLE.md) · [How it works](HOW_IT_WORKS.md)
