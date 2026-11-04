/**
 * When Kriko opens on a blank chat. A launch always does; a resume does after a
 * real absence, never over a turn that is still being written, and never when
 * there is no open conversation to replace.
 */

import assert from 'node:assert/strict';

import { FRESH_CHAT_AFTER_MS, startsFreshChat } from '../src/engine/freshchat';

const open = { streaming: false, hasActiveChat: true };

function aShortTripToAnotherAppKeepsTheChat(): void {
  assert.equal(startsFreshChat({ ...open, awayMs: 0 }), false);
  assert.equal(startsFreshChat({ ...open, awayMs: 30_000 }), false);
  assert.equal(startsFreshChat({ ...open, awayMs: FRESH_CHAT_AFTER_MS - 1 }), false);
}

function aRealAbsenceOpensABlankChat(): void {
  assert.equal(startsFreshChat({ ...open, awayMs: FRESH_CHAT_AFTER_MS }), true);
  assert.equal(startsFreshChat({ ...open, awayMs: 3 * 60 * 60 * 1000 }), true);
}

function anAnswerBeingWrittenIsNeverTakenAway(): void {
  assert.equal(startsFreshChat({ awayMs: 3 * 60 * 60 * 1000, streaming: true, hasActiveChat: true }), false);
}

function withNoOpenChatThereIsNothingToReplace(): void {
  assert.equal(startsFreshChat({ awayMs: 3 * 60 * 60 * 1000, streaming: false, hasActiveChat: false }), false);
}

function anUnreadableClockNeverWipesTheChat(): void {
  assert.equal(startsFreshChat({ ...open, awayMs: Number.NaN }), false);
  assert.equal(startsFreshChat({ ...open, awayMs: Number.POSITIVE_INFINITY }), false);
}

aShortTripToAnotherAppKeepsTheChat();
aRealAbsenceOpensABlankChat();
anAnswerBeingWrittenIsNeverTakenAway();
withNoOpenChatThereIsNothingToReplace();
anUnreadableClockNeverWipesTheChat();
process.stdout.write('Fresh chat checks passed.\n');
