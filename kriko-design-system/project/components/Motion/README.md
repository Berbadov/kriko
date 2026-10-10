Motion explains state and gives feedback; it is never decoration. The tokens are not a token family (the format has no motion type), so they live in `components/bundle.css`: `--dur-press` 90ms, `--dur-quick` 160ms, `--dur-base` 260ms, `--dur-slow` 600ms, `--dur-loop` 1600ms, `--ease-out` `cubic-bezier(.2,.8,.2,1)` for feedback and `--ease-mech` `cubic-bezier(.3,1.25,.5,1)` for parts that settle like hardware.

Rules:

- Presses change colour, they do not move: keys and plates shift fill in `--dur-press` (90ms).
- Selection slides: thumbs and switch knobs move on `--ease-mech` in `--dur-base`; a lit LED fades in `--dur-quick`.
- Loops run only while their condition is true: LIVE scan, the meter head and NEEDS YOU blink stop the moment the state changes.
- LEDs boot once on mount (`--dur-slow`) and are static afterwards.
- Never animate tables or text. A count may push up once when a write lands; nothing else about data moves.
- Under `prefers-reduced-motion: reduce` there are no loops and no flicker: show the final lit state and cut transitions to zero.

The loading mark is the jack lifting: the K's two arms swing toward each other over 2.6s with an easing in and out, the screw nub slides 8 units back, the thread turns and the wing nut spins. The asset store removes animation from SVG files, so the animated mark is kept as inline markup in the Motion preview: copy it from there for loaders and splash screens.


The full spec is `Motion.md`; the interactive reference, including the agent pipeline scene, is `MotionLab`.
