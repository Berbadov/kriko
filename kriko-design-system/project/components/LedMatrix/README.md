Use the LED matrix as the system's indicator: a grid of square dots, lit dots in a state colour with a soft glow, unlit dots in `led-off`, seated in a `well` tile (`shadow-well`). The 8x8 size is for tiles and hero buttons; 5x5 sits inside tags and segmented controls.

Lit colours are `brand-bright` (identity), `ice` (live, done), `#fff` (needs you on brand), `led-dim` (idle) and `danger`. Never use more than one lit colour per tile.

Glyphs, `#` lit and `.` unlit:

```
K        check     bang      x
.......  ........  ...##...  #......#
.#...#.  ........  ...##...  .#....#.
.#..#..  ......#.  ...##...  ..#..#..
.#.#...  .....##.  ...##...  ...##...
.##....  #...##..  ...##...  ...##...
.#.#...  ##.##...  ........  ..#..#..
.#..#..  .###....  ...##...  .#....#.
.#...#.  ..#.....  ...##...  #......#
```

5x5: bang `..#.. ..#.. ..#.. ..... ..#..`, check `....# ...#. #.#.. .#... .....`, cross `#...# .#.#. ..#.. .#.#. #...#`, queued `..... ..... #.#.# ..... .....`.

Motion: on first mount a tile boots with a 600ms flicker (`k-boot`, 9ms stagger per dot) that resolves into the glyph; LIVE animates as an equaliser of rising and falling columns; NEEDS YOU and QUEUED blink at 1600ms with a hard step, not a fade. All of it stops under `prefers-reduced-motion` and shows the lit glyph.
