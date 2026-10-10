Dithered blue skies for page heroes, made with an 8x8 Bayer ordered dither over the KRIKO blue ramp (`ground`, `brand-deep`, `brand-low`, `brand`, a lighter blue, `brand-bright`, `ice`, white). Clouds sit on the right so the title and lead on the left always read on `brand` blue; the last fifth of every image dithers down into `ground`, so the hero meets the page without a gradient overlay. These are raster files: use them with `<img>` in HTML or `img()` in GPUI, never as tiled backgrounds.

- `sky-hero.png` (1920x600): Home and About, the most clouds.
- `sky-wide.png` (1920x480): Local LLM and other pages with a frosted card in the hero.
- `sky-dim.png` (1920x360): every other tab, almost clear sky.

`sky.py` regenerates them (numpy and Pillow). Change the seed to get a new sky, and keep the left half clear. The images are drawn at 4x pixel size; scale to the hero width with `Cover` and check the dots stay square.

## Shimmer (moving sky)

`shimmer.py` bakes the same sky as a loopable frame strip with leaf shadows sweeping over it, like sun through a tree branch. Far leaves sway slowly, near leaves faster, two branch lines creak. `python3 shimmer.py` writes 128 frames (Calm, 16 s loop at 8 fps); `python3 shimmer.py breezy` writes 85 frames (wider sway, 1.5x speed). Each frame is 1200x304 with square pixels. In GPUI, load the frames once as image sources and step through them with `with_animation`; do not redraw the dither per frame. Under reduce motion show frame 00 only. Live version: MotionLab, section 00.
