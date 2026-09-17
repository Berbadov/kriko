# Use the mark

Everything the product shows — the toolbar tile, the taskbar icon, the favicon,
the rail — comes from one file. Change that file, run one script, commit what it
wrote.

```bash
python packaging/render_icon.py
python packaging/render_lockup.py
```

```
logo-mark.svg (16x16) -> tauri/src-tauri/icons/icon.png (1024px)
logo-mark.svg -> ui/public/mark.svg
logo-mark.svg -> extension/assets/icons/icon-{16,32,48,128}.png
logo-mark.svg + KRIKO -> extension/assets/logo-lockup.svg
logo-mark.svg + KRIKO -> extension/assets/logo-lockup-mono.svg
```

> **The tests fail and you did not touch the mark.**
> Then somebody edited an output. Every file on the right of those arrows is
> generated; re-run both scripts and commit the result. If a test still fails,
> the edit was to `extension/assets/logo-mark.svg` and was not re-rendered.

---

## Which file to reach for

| You want | Use | Where it comes from |
|---|---|---|
| An app or browser icon | `extension/assets/icons/icon-*.png` | rendered |
| A favicon, or the rail | `ui/public/mark.svg` | rendered |
| The logo with the name | `extension/assets/logo-lockup.svg` | rendered |
| The logo on a ground that is not ours | `extension/assets/logo-lockup-mono.svg` | rendered |
| To change any of the above | `extension/assets/logo-mark.svg` | **the source** |

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

## The grid

The mark is a 16×16 grid of rectangles. Pixel art that happens to be written as
SVG — which is why it is rasterised by an integer nearest-neighbour scale and
never handed to a general renderer. Any antialiasing smears it.

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
