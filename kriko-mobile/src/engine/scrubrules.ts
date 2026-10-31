/**
 * The arithmetic of the thumb-side scroll rail: where the handle sits for a
 * scroll position, and which scroll position a handle position means. Pure, so
 * the ends, the clamps and the round trip are tested without a screen.
 */

/** The rail appears once the conversation is this many screens long. */
export const SCRUB_MIN_RATIO = 1.6;
/** The grabbable part of the rail, in dp. */
export const SCRUB_HANDLE_H = 44;
const SCRUB_RAIL_MIN = 140;
const SCRUB_RAIL_MAX = 300;

function clamp(value: number, low: number, high: number): number {
  return Math.min(Math.max(value, low), high);
}

/** True when the content is long enough to be worth a rail. */
export function scrubEligible(content: number, viewport: number): boolean {
  return viewport > 0 && content >= viewport * SCRUB_MIN_RATIO;
}

/** The rail takes the lower half of the list, within reach of a thumb. */
export function railHeight(viewport: number): number {
  return Math.round(clamp(viewport * 0.5, SCRUB_RAIL_MIN, SCRUB_RAIL_MAX));
}

export function scrollRange(content: number, viewport: number): number {
  return Math.max(0, content - viewport);
}

/** How far the handle can travel inside the rail. */
export function handleTravel(rail: number, handle = SCRUB_HANDLE_H): number {
  return Math.max(0, rail - handle);
}

/** The handle's top edge for a scroll offset. */
export function handleTopFor(
  offset: number, content: number, viewport: number, rail: number, handle = SCRUB_HANDLE_H,
): number {
  const range = scrollRange(content, viewport);
  const travel = handleTravel(rail, handle);
  if (range <= 0 || travel <= 0) return 0;
  return clamp(offset / range, 0, 1) * travel;
}

/** The scroll offset a handle top edge stands for. */
export function offsetForHandleTop(
  top: number, content: number, viewport: number, rail: number, handle = SCRUB_HANDLE_H,
): number {
  const range = scrollRange(content, viewport);
  const travel = handleTravel(rail, handle);
  if (range <= 0 || travel <= 0) return 0;
  return clamp(top / travel, 0, 1) * range;
}

/** Where the finger puts the handle: centred on it, or kept where it was grabbed. */
export function clampHandleTop(top: number, rail: number, handle = SCRUB_HANDLE_H): number {
  return clamp(top, 0, handleTravel(rail, handle));
}

/** Whole percent of the way down the conversation, for the hint. */
export function percentThrough(offset: number, content: number, viewport: number): number {
  const range = scrollRange(content, viewport);
  if (range <= 0) return 0;
  return Math.round(clamp(offset / range, 0, 1) * 100);
}
