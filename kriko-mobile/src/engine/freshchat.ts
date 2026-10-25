/**
 * When Kriko opens on a blank chat instead of the one the reader left.
 *
 * A launch always starts fresh: the previous conversation is one tap away in
 * History, but the first thing on the screen is a place to scan or ask. A
 * resume is the same thing after a real absence. A short trip to another app
 * (checking a price, copying a link) keeps the chat, and an answer that is
 * still being written is never taken away from under the reader.
 */

/** How long the app must have been out of sight before a resume starts fresh. */
export const FRESH_CHAT_AFTER_MS = 5 * 60 * 1000;

export function startsFreshChat(input: {
  /** Milliseconds since the app left the foreground. */
  awayMs: number;
  /** A turn is being written right now. */
  streaming: boolean;
  /** A conversation is open; with none open there is nothing to replace. */
  hasActiveChat: boolean;
}): boolean {
  if (!input.hasActiveChat || input.streaming) return false;
  return Number.isFinite(input.awayMs) && input.awayMs >= FRESH_CHAT_AFTER_MS;
}
