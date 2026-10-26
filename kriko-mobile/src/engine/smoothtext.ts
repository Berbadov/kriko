/**
 * Showing a streamed answer at a steady pace instead of in the chunks the
 * network happens to deliver. The pace follows the backlog (the further behind,
 * the faster), so it never trails the stream by much and never runs out and
 * stutters. The cut always lands between words, and Markdown the reader has not
 * seen finish is held back or closed, so `**` and `[1` never flash as symbols.
 */

/** Time constant of the catch-up while the answer is still arriving. */
export const REVEAL_TAU_MS = 300;
/** Time constant once the answer has finished: whatever is left goes quickly. */
export const REVEAL_DRAIN_TAU_MS = 100;
/** Never slower than this, so a small backlog still finishes. */
export const REVEAL_MIN_CPS = 80;
/** A frame that took longer than this (a stall) counts as this long. */
export const REVEAL_MAX_STEP_MS = 64;
/** A word longer than this (a link) may be cut mid-way. */
const WORD_LIMIT = 24;
/** An unfinished link or citation is held back for at most this many characters. */
const HOLD_LIMIT = 140;

/** Characters shown after `dt` more milliseconds. Fractional; the caller floors it. */
export function advance(shown: number, total: number, dt: number, draining: boolean): number {
  if (shown >= total) return total;
  const tau = draining ? REVEAL_DRAIN_TAU_MS : REVEAL_TAU_MS;
  const lag = (total - shown) * (1 - Math.exp(-dt / tau));
  const floor = (REVEAL_MIN_CPS * dt) / 1000;
  return Math.min(total, shown + Math.max(lag, floor));
}

function isSpace(char: string | undefined): boolean {
  return char === undefined || /\s/.test(char);
}

/** How many times `marker` occurs in `text`. */
function count(text: string, marker: string): number {
  return text.split(marker).length - 1;
}

/** Pull `end` back past anything the reader would see half-written. */
function settle(text: string, from: number): number {
  let end = from;
  // A citation or link that has not closed yet: "[1", "[site](https://exa". A
  // stray "[" that never closes must not hold the rest of the answer back.
  const open = text.lastIndexOf('[', end - 1);
  if (open >= 0 && end - open <= HOLD_LIMIT) {
    const tail = text.slice(open, end);
    if (/^\[[^\]]*$/.test(tail) || /^\[[^\]]*\]\([^)]*$/.test(tail)) end = open;
  }
  // A line that is only the start of a heading, bullet, number or quote.
  const lineStart = end === 0 ? 0 : text.lastIndexOf('\n', end - 1) + 1;
  if (/^\s*(#{1,4}|[-*•]|\d{1,2}[.)]|>)\s*$/.test(text.slice(lineStart, end))) end = lineStart;
  // A bold or code opener with nothing after it yet.
  const head = text.slice(0, end);
  const dangling = head.match(/(\*\*|`)\s*$/);
  if (dangling && count(head, dangling[1]) % 2 === 1) end = dangling.index ?? end;
  return end;
}

/**
 * How much of `text` to draw when the pace has reached `limit` characters.
 * `done` is the finished answer, which is always drawn whole.
 */
export function revealEnd(text: string, limit: number, done: boolean): number {
  if (done && limit >= text.length) return text.length;
  let end = Math.min(Math.max(Math.floor(limit), 0), text.length);
  if (end < text.length && !isSpace(text[end]) && !isSpace(text[end - 1])) {
    const window = text.slice(Math.max(0, end - WORD_LIMIT), end);
    const space = window.search(/\s\S*$/);
    if (space >= 0) end = Math.max(0, end - WORD_LIMIT) + space;
  }
  return trimmed(text, settle(text, trimmed(text, end)));
}

/** The cut sits at the end of a word; the space or line break belongs to the next one. */
function trimmed(text: string, from: number): number {
  let end = from;
  while (end > 0 && end < text.length && /[ \t\n]/.test(text[end - 1])) end -= 1;
  return end;
}

/** The prefix, with any bold or code span still open closed in the order it opened. */
export function closeOpen(prefix: string): string {
  const bold = count(prefix, '**') % 2 === 1;
  const code = count(prefix, '`') % 2 === 1;
  if (bold && code) {
    return prefix.lastIndexOf('**') > prefix.lastIndexOf('`') ? `${prefix}**\`` : `${prefix}\`**`;
  }
  if (bold) return `${prefix}**`;
  if (code) return `${prefix}\``;
  return prefix;
}

/** What the reader sees: the finished text whole, a running one cut and closed. */
export function visibleText(text: string, end: number, done: boolean): string {
  if (done && end >= text.length) return text;
  return closeOpen(text.slice(0, Math.min(end, text.length)));
}
