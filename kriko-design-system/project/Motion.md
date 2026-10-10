# Motion

Quiet hardware by default: short, mechanical, and completely still when nothing is happening. Loud only when something needs you or a run finishes. The interactive reference is `MotionLab` in Foundations; this file is the spec behind it. The CSS versions live in `components/bundle.css` and in the lab source.

## Timings

| Moment | Time | Curve | Rule |
| --- | --- | --- | --- |
| Key press | 90 ms in, 160 ms back | ease-out | flat fill: `brand` to `brand-low`, no travel |
| Plate press | 90 ms in, 160 ms back | ease-out | flat fill: `bezel-lo` to `well`, no travel |
| Hover, focus, colour | 160 ms | ease-out | colour and glow only, never size |
| Slides: segmented thumb, switch knob, nav well | 260 ms | ease-mech | overshoots about 4 percent, then settles |
| Hero title | 420 ms | 14 hard steps | wipes left to right on tab change only |
| Card rise | 260 ms, 50 ms stagger | ease-out | 12 px and opacity, on tab change only |
| LED boot | 600 ms | steps | once on mount, 9 ms between dots |
| Loops: scan, breathe, blink | 1.2 s, 2.4 s, 1.6 s | linear or steps | run only while their state is true |
| Meter fill | 14 ms per segment | steps | left to right, last segment blinks |
| Loud moment | 360 ms flash, 1.6 s pulse | 4 steps, ease-out | see below |

`ease-out` is `cubic-bezier(.2,.8,.2,1)`, `ease-mech` is `cubic-bezier(.3,1.25,.5,1)`. Nothing else is allowed: no spring libraries, no bounce on text, no animation on tables.

## Loud moments

Four, and only four. A fifth means something else is not quiet enough.

1. **Needs you.** The tag and the rail card get a brand halo that pulses outwards every 1.6 s until the user acts.
2. **Disputed claim.** Two cubes hold above the database with a pixel bang over them, one 360 ms brand flash, a 8-frame camera shake, then both are written and marked disputed.
3. **Run done.** One 360 ms flash, the check glyph is drawn in 40 ms steps and ends on one ice flash.
4. **Hold to confirm.** Destructive buttons charge in 24 hard steps over 1.2 s; releasing early drains in 160 ms.

## Quirks worth keeping

The first three and the sky shimmer are in the lab; the typed file name and the two LED K ideas are proposals.

- Counts push up 160 ms when a write lands and the row washes `brand` for 700 ms. This is the one place a number moves; the rule is "never animate data values", except a count that just changed.
- The sidebar well slides between items instead of jumping.
- The brand block boots its LED K once at launch, then stays still.
- While a file is being written its name types out in mono at 30 ms a character.
- Hero skies carry the leaf-shadow shimmer below. Empty states may use the same strip. Never behind data.
- Idle for five minutes: one LED K scans across the screen at 5 fps. Any input stops it.

## Agent pipeline scene

A low-poly flat-shaded loop, 10 s, for the Run screen and empty states. Four stations on a floor grid: a wireframe globe (fetch), a page (read), cubes (extract) and a three-disc SQLite cylinder (write). One page flies from the globe to the reading spot on an arc, a bright line scans down it and lights the lines under it, four of those lines pop out as cubes and hop to the cylinder, each landing lights one slot on the cylinder and the counters tick.

| Stage | Window | Caption |
| --- | --- | --- |
| Fetch | 0.0 to 1.8 s | `GET site` then status and size |
| Read | 1.8 to 4.2 s | scanning N lines, then N claims found |
| Extract | 4.1 to 7.5 s | each claim keeps its source line |
| Write | 6.15 to 8.2 s | inserting claims, evidence and source rows, then committed |

The disputed variant adds 1.5 s: the last two cubes hover side by side until the flash, shake and bang have played, then drop in. Palette is the blue ramp only: `brand-deep`, `brand-low`, `brand`, `brand-hover`, `brand-bright`, `ice`. Faces are shaded with four to six levels from one light, edges are 1 px `ice`. Fades are done by scaling to zero, never by transparency, so the picture stays crisp.

The lab draws it in about 150 lines of canvas code at 360 by 132 pixels, scaled up with nearest neighbour, with a hard alpha threshold to remove edge blur. Treat that file as the reference for geometry and timing.

## Sky shimmer

Hero skies move like sun through a tree: dithered shadows of leaves drift over the clouds. Not waves. Two layers of leaves sit along two branch lines, far leaves (11, big, soft, slow) and near leaves (14, small, darker, twice as fast). Each leaf sways a few pixels, turns up to 26 degrees and wobbles on a second harmonic, and the two branch lines creak a few pixels. The result is subtracted from the cloud value before the 8x8 Bayer dither, so every shadow edge is ordered dots in the blue ramp, never a gradient.

| Setting | Calm (default) | Breezy |
| --- | --- | --- |
| Sway | 3 to 5 px | twice that |
| Speed | 16 s loop | 10.7 s loop |
| Redraw | 15 fps stepped in the lab, 8 fps baked | same |
| Reduce motion | frame 00, frozen | frame 00, frozen |

Both branches start at the right edge, so the title area stays mostly clear `brand` blue; check any new seed against the lead text for contrast. In GPUI do not dither live. Run `assets/Sky/shimmer.py` once to bake 128 frames (85 for Breezy), load them as image sources and step through them with `with_animation(...).repeat()`, quantising `delta` to the frame count. Pause the animation when the window is unfocused or the hero is scrolled out of view. Both loops close exactly: the first and last frame match.

## Process scenes

The pipeline scene above runs everything on one stage. Each process also has its own scene, one idea per scene, so the Run screen can show whichever agent step is active and the empty states can borrow one. All five use the same engine, camera and palette, 360 by 132 pixels, nearest-neighbour scaling, and loop. The lab has a tab per scene next to Full run.

| Scene | Length | What happens | Loud moment |
| --- | --- | --- | --- |
| Plan | 7 s | A root cube grows four question nodes and eight source leaves. A light wave runs outwards along the branches, then everything collapses into the root. | none |
| Read | 7 s | A wire globe emits pages on arcs. Each page is scanned by a bright line, claim lines light as it passes, then it exits right. A request ring pulses on the globe on every fetch. | none |
| Extract | 7 s | A page on the left, a gate arch in the middle with a sweeping line, a four-slot shelf on the right. Claim lines peel off the page, turn into cubes as they cross the gate and land on the shelf with a bounce, each landing lights its slot. | none |
| Cross-check | 8 s | A balance scale. Pair one matches: the cubes fuse, evidence discs stack, a ring closes. Pair two differs: the beam tilts, flash, shake and pixel bang play, a dashed link joins both cubes and both are kept, marked disputed. | the dispute |
| Write | 8 s | A transaction plate and five cylinders in a row: subjects, attributes, claims, evidence, sources. Cubes arc in and fill each table, then one commit ring sweeps down all five and a flash closes the run. Counters show rows per table. | the commit |

Captions in the HUD use the same words as the Run screen: `plan`, `read`, `extract`, `cross-check`, `write`. No scene shows a product name, a score or a winner. Cross-check ends with both claims kept, never with one side chosen. Reduce motion draws each scene's last stable frame (at 88 percent of its length).

## In GPUI

Checked against the gpui 0.2.2 source, not compiled in this pass.

- Tweens: `AnimationExt::with_animation(id, Animation::new(duration).with_easing(f), |el, delta| ...)`. `.repeat()` for loops. Built in easings are `linear`, `quadratic`, `ease_in_out`, `ease_out_quint()`, `bounce(f)` and `pulsating_between(a, b)`. Write ease-mech as a small closure over a cubic Bezier.
- Opacity is `.opacity(f32)` on any styled element. A `div` cannot rotate or scale, so a key's press is a background colour change, and tumbling things are painted as polygons.
- Hard steps (title wipe, meter fill, stamp) are a timer that sets state, or `delta` quantised in the animation closure: `(delta * 14.0).floor() / 14.0`.
- LED loops are state on a timer that calls `cx.notify()`. Start the timer when the state becomes true and drop it the moment it changes, so an idle app does no work.
- The 3D scene is a `canvas(prepaint, paint)` element. Each frame project the vertices, sort faces far to near, and for each face build a `PathBuilder::fill()` with `move_to`, `line_to`, `close`, `build` and call `window.paint_path(path, colour)`. About 600 faces per frame. Snap projected points to a 3 px grid to get the chunky pixel edges; call `window.request_animation_frame()` only while the scene is visible and the window is focused.
- Reduced motion: a settings flag read once. When set, loops never start, transitions have zero duration and the scene draws its last frame.
- Budget: a frame must stay under 2 ms of CPU, loops cap at 30 fps, and nothing animates in an unfocused or hidden window.
