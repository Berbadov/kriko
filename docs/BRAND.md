# Use the mark

Everything the product shows — the toolbar tile, the taskbar icon, the favicon,
the rail — is generated. Change a source, run one script, commit what it wrote.

```bash
python packaging/render_icon.py
python packaging/render_lockup.py
```

```
logo-mark.svg (16x16)       -> extension/assets/icons/icon-{16,32,48,128}.png
logo-mark.svg               -> ui/public/mark.svg
logo-mark-large.svg (64x64) -> tauri/src-tauri/icons/icon.png (1024px)
logo-mark.svg + KRIKO       -> extension/assets/logo-lockup.svg
logo-mark.svg + KRIKO       -> extension/assets/logo-lockup-mono.svg
```

**Two sources, and only two.** The small one is pixel art and the large one is
not; [Two marks, one design](#two-marks-one-design) is why. Everything else on
the right of those arrows is output.

> **The tests fail and you did not touch the mark.**
> Then somebody edited an output. Every file on the right of those arrows is
> generated; re-run both scripts and commit the result. If a test still fails,
> the edit was to one of the two sources and was not re-rendered.

---

## Which file to reach for

| You want | Use | Where it comes from |
|---|---|---|
| A browser toolbar icon | `extension/assets/icons/icon-*.png` | rendered |
| A favicon, or the rail | `ui/public/mark.svg` | rendered |
| The app icon everything else derives from | `tauri/src-tauri/icons/icon.png` | rendered |
| The logo with the name | `extension/assets/logo-lockup.svg` | rendered |
| The logo on a ground that is not ours | `extension/assets/logo-lockup-mono.svg` | rendered |
| To change the mark at 48px and below | `extension/assets/logo-mark.svg` | **a source** |
| To change the mark at 128px and above | `extension/assets/logo-mark-large.svg` | **a source** |

The monochrome lockup fills with `currentColor` and paints no ground. It
inherits the colour of whatever it is dropped into, which is the only thing
that is correct on both a white README and a dark panel.

## The three colours

They are the panel theme's, not the mark's. `ui/src/styles/themes/panel.css`
owns them and the mark borrows them, so a mark can never sit on the rail as a
foreign object — which is exactly how the lemon it replaced read.

| Role | Token | Value |
|---|---|---|
| Ground | `--n-2` | `#15171C` |
| Letter | `--n-9` | `#E7E9ED` |
| The rising arm | `--accent` | `#E8C04B` |

Move one and the other has to follow: a test asserts the mark's hex values and
the theme's token definitions agree.

## Two marks, one design

The grid below is right about its own size and wrong about every other one.
Nearest-neighbour is the only scale that keeps pixel art intact, so at 1024px
each of its sixteen cells becomes a 64px square — and the installer icon the
reader double-clicks was eight hard blocks with visible stair-steps. Their
verdict was "pixelated and very ugly", and at that size they were right: a
favicon technique was being asked to be a product icon.

So the mark is drawn twice.

| Size | Source | How it is rasterised |
|---|---|---|
| 16, 32, 48, 128px — toolbar, favicon | `logo-mark.svg` | integer nearest-neighbour, three colours exactly |
| 1024px master — installer, taskbar, rail | `logo-mark-large.svg` | scanline fill, 4× supersampled, real diagonals |

Same letter, same three colours, same idea — a slab stem with the accent arm
rising out of it. What differs is only what each size can carry: below 48px a
true diagonal is four grey pixels and reads as blur, and above 128px a stepped
one reads as a mistake.

The large mark's vocabulary is `rect` and `polygon` and nothing else, because
`packaging/render_icon.py` writes out its own rasteriser and imports nothing. A
`path` would mean a bezier flattener in a build script — the door that stays
shut, the same trade `kriko/adapters.py` makes about what a pack may express.

Two files drawing one letter is exactly the failure this page exists to
prevent, so it is tested rather than trusted: the colour test reads both marks
and fails if a hex moves in one and not the other, and
`test_the_app_icon_is_actually_antialiased` counts distinct colours in the
committed master — three means somebody pointed it back at the grid.

## The grid

The small mark is a 16×16 grid of rectangles. Pixel art that happens to be
written as SVG — which is why it is rasterised by an integer nearest-neighbour
scale and never handed to a general renderer. Any antialiasing smears it.

Cap height is 14 cells, the stroke is 3. The wordmark uses both, because it is
drawn on the same grid rather than set in a typeface. That is deliberate: it
renders identically with no font file and no network, it cannot drift when the
app's display face changes, and it reads as the same object as the icon.

Clear space around the lockup is one stroke — 3 cells — on every side. Between
the mark and the word it is 10, wider than the letter tracking, because at a
normal gap the eye reads the mark as a sixth letter and the wordmark becomes
"KKRIKO".

## Why it looks like this

A slab K, and the upper arm is the accent.

**Slab because of 16 pixels.** The favicon is the size the mark is seen at most
often, and a letter drawn in hairlines closes into a smudge there. Mass
survives. Every stroke is three cells for the same reason.

**The accent is a whole arm, not a joint.** An earlier draft put the amber on
one terminal block; below about 48px it read as a detached square, because a
corner touch is not a join. Taking the whole upper arm gives the mark a stroke
that rises out of the letter the way a step chart does — which is the product
in a glyph. Kriko exists to say what is going wrong with the thing you are
looking at, and the amber is the colour the panel already reserves for that.

## Next

- [How the docs are written](STYLE.md)
- [How it works](HOW_IT_WORKS.md) — four diagrams
