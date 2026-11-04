import { useEffect, useRef, useState } from 'react';

import { REVEAL_MAX_STEP_MS, advance, revealEnd, visibleText } from '../engine/smoothtext';
import { useReducedMotion } from './Motion';

/**
 * A streamed answer at a steady pace. `live` is true while the answer is still
 * arriving; once it is false whatever is left drains quickly. A finished answer
 * that mounts already complete (history, a reopened chat) is shown whole, and so
 * is everything when the reader asks for reduced motion.
 *
 * `settled` is true only when the answer is finished *and* fully drawn, which
 * is when the things that belong under it (copy, sources) may appear.
 */
export function useSmoothText(text: string, live: boolean): { text: string; settled: boolean } {
  const reduced = useReducedMotion();
  const instant = reduced !== false;
  const [end, setEnd] = useState(() => (live && !instant ? 0 : text.length));
  const position = useRef(end);

  useEffect(() => {
    if (instant) {
      // The render below already draws everything; just keep the pace in step.
      position.current = text.length;
      return undefined;
    }
    // A replaced, shorter text must not leave the pace beyond its end.
    if (position.current > text.length) position.current = text.length;
    let frame = 0;
    let last = 0;
    const tick = (now: number) => {
      const dt = last ? Math.min(now - last, REVEAL_MAX_STEP_MS) : 16;
      last = now;
      position.current = advance(position.current, text.length, dt, !live);
      const next = revealEnd(text, position.current, !live);
      // Only a new word re-renders the answer, not every frame.
      setEnd((current) => (current === next ? current : next));
      if (position.current < text.length) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [text, live, instant]);

  const shown = instant ? text.length : Math.min(end, text.length);
  return {
    text: visibleText(text, shown, !live),
    settled: !live && shown >= text.length,
  };
}
