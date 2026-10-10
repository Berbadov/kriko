Use for state on rows and headers. A tag is a recessed `well` capsule holding a 5x5 LED glyph and one uppercase word in `mono-label`: LIVE (scanning bars, `ice`), NEEDS YOU (blinking bang on a brand fill, the only filled tag), QUEUED (blinking dots, `led-dim`), DONE (check, `ink-2`), BLOCKED (cross, `danger` on `danger-wash`).

The glyph never replaces the word. The consumer provides the state and the word. At most one NEEDS YOU is visible per card. Glyph bitmaps are listed in the LedMatrix guidelines.
