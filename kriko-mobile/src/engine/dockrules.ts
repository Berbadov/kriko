/**
 * When the bottom bar steps out of the way. It leaves once the reader has moved
 * down through text and comes back on the first move up, at the top of a page,
 * or whenever the page is too short to scroll. Kept apart from the screens so
 * every threshold is tested without a phone.
 */

/** Pixels of travel down from the last turning point before the bar leaves. */
export const DOCK_HIDE_AFTER = 24;
/** Pixels of travel back up before it returns; smaller, so it is easy to find. */
export const DOCK_SHOW_AFTER = 10;
/** At or above this offset the bar is always there. */
export const DOCK_TOP_EDGE = 12;
/** A page that scrolls less than this never hides it. */
export const DOCK_MIN_SCROLL = 120;
/** A toggle holds this long: the bar is still moving and the page resizes under it. */
export const DOCK_SETTLE_MS = 320;
/** One event this far apart is a jump the app made, not a finger. */
export const DOCK_JUMP = 500;

export interface DockMetrics {
  offset: number;
  viewport: number;
  content: number;
}

export interface DockState {
  hidden: boolean;
  /** Where the current direction of travel began. */
  anchor: number;
  last: number;
  direction: -1 | 0 | 1;
  /** The viewport the offsets were measured in; a change is a layout, not a scroll. */
  viewport: number;
  lockedUntil: number;
}

export const initialDock: DockState = {
  hidden: false,
  anchor: 0,
  last: 0,
  direction: 0,
  viewport: 0,
  lockedUntil: 0,
};

/**
 * The next state after one scroll event. `user` is false when the app itself
 * moved the list (following a streamed answer, opening a chat at its end): the
 * position is followed but never counts as the reader asking for room.
 */
export function nextDock(state: DockState, metrics: DockMetrics, now: number, user = true): DockState {
  const range = Math.max(0, metrics.content - metrics.viewport);
  const offset = Math.min(Math.max(metrics.offset, 0), range);
  const rebased: DockState = { ...state, viewport: metrics.viewport, anchor: offset, last: offset, direction: 0 };

  if (range < DOCK_MIN_SCROLL) return { ...rebased, hidden: false };
  // Hiding the bar makes the list taller, which moves the offset by itself.
  // Treating that as a scroll would show the bar again, and so on forever.
  if (Math.abs(metrics.viewport - state.viewport) > 1) return rebased;
  if (offset <= DOCK_TOP_EDGE) {
    return { ...rebased, hidden: false, lockedUntil: state.hidden ? now + DOCK_SETTLE_MS : state.lockedUntil };
  }
  const delta = offset - state.last;
  if (!user || Math.abs(delta) > DOCK_JUMP) return rebased;
  if (delta === 0) return state;

  const direction: 1 | -1 = delta > 0 ? 1 : -1;
  const anchor = direction === state.direction ? state.anchor : state.last;
  const moved: DockState = { ...state, last: offset, anchor, direction };
  if (now < state.lockedUntil) return moved;

  const travel = offset - anchor;
  if (!state.hidden && travel >= DOCK_HIDE_AFTER) {
    return { ...moved, hidden: true, anchor: offset, lockedUntil: now + DOCK_SETTLE_MS };
  }
  if (state.hidden && -travel >= DOCK_SHOW_AFTER) {
    return { ...moved, hidden: false, anchor: offset, lockedUntil: now + DOCK_SETTLE_MS };
  }
  return moved;
}
