/**
 * When the bottom bar leaves and returns. It goes when the reader moves down
 * through text, comes back on the first move up, and never fights the layout
 * change its own leaving causes.
 */

import assert from 'node:assert/strict';

import {
  DOCK_HIDE_AFTER,
  DOCK_JUMP,
  DOCK_SETTLE_MS,
  DOCK_SHOW_AFTER,
  initialDock,
  nextDock,
  type DockMetrics,
  type DockState,
} from '../src/engine/dockrules';

const VIEWPORT = 700;
const LONG = 5000;
const page = (offset: number, content = LONG, viewport = VIEWPORT): DockMetrics => ({ offset, viewport, content });

/** Feed a list of offsets one frame apart (16 ms), as a finger would. */
function drag(from: DockState, offsets: number[], start = 1000, content = LONG): DockState {
  let state = from;
  let now = start;
  for (const offset of offsets) {
    state = nextDock(state, page(offset, content), now);
    now += 16;
  }
  return state;
}

function settled(offset: number): DockState {
  // The first event of a page only records its viewport.
  return nextDock(initialDock, page(offset), 0);
}

function aShortPageNeverHidesTheBar(): void {
  const state = drag(settled(0), [0, 20, 40, 60, 80], 1000, VIEWPORT + 60);
  assert.equal(state.hidden, false);
}

function movingDownPastTheThresholdHidesIt(): void {
  const almost = drag(settled(200), [210, 220, 200 + DOCK_HIDE_AFTER - 1]);
  assert.equal(almost.hidden, false);
  const enough = drag(settled(200), [210, 220, 200 + DOCK_HIDE_AFTER]);
  assert.equal(enough.hidden, true);
}

function theFirstMoveBackUpBringsItBack(): void {
  const hidden = drag(settled(200), [240, 280, 320]);
  assert.equal(hidden.hidden, true);
  const later = drag({ ...hidden, lockedUntil: 0 }, [320 - DOCK_SHOW_AFTER + 1], 2000);
  assert.equal(later.hidden, true);
  const shown = drag({ ...hidden, lockedUntil: 0 }, [320 - DOCK_SHOW_AFTER], 2000);
  assert.equal(shown.hidden, false);
}

function aTurnResetsHowFarTheReaderHasTravelled(): void {
  // 20 down, a little up, 20 down again: no single run reached the threshold.
  const state = drag(settled(200), [210, 220, 215, 225, 235]);
  assert.equal(state.hidden, false);
}

function theTopOfAPageAlwaysShowsIt(): void {
  const hidden = drag(settled(200), [240, 280, 320]);
  assert.equal(hidden.hidden, true);
  // Even inside the settle window: the reader is back at the top.
  const top = nextDock(hidden, page(0), hidden.lockedUntil - 1);
  assert.equal(top.hidden, false);
}

function aToggleHoldsWhileTheBarMoves(): void {
  const hidden = drag(settled(200), [240, 280, 320], 1000);
  assert.equal(hidden.hidden, true);
  // A reversal right away is ignored: the bar is still animating.
  const quick = nextDock(hidden, page(250), hidden.lockedUntil - 1);
  assert.equal(quick.hidden, true);
  // The same reversal after the bar settled counts.
  const slow = nextDock(hidden, page(250), hidden.lockedUntil + DOCK_SETTLE_MS);
  assert.equal(slow.hidden, false);
}

function aLayoutChangeIsNotAScroll(): void {
  // Hiding the bar makes the list taller and, at the bottom, moves the offset
  // up by itself. That must not bring the bar straight back.
  const hidden = drag(settled(4200), [4240, 4280, 4300], 1000);
  assert.equal(hidden.hidden, true);
  const resized = nextDock(hidden, page(4250, LONG, VIEWPORT + 56), hidden.lockedUntil + 1000);
  assert.equal(resized.hidden, true);
  // The offset was clamped to the taller list's end; moving up from there, in
  // the new viewport, is the reader again.
  const after = nextDock(resized, page(resized.last - DOCK_SHOW_AFTER, LONG, VIEWPORT + 56), hidden.lockedUntil + 1100);
  assert.equal(after.hidden, false);
}

function aJumpTheAppMadeIsNotTheReader(): void {
  const jumped = nextDock(settled(0), page(DOCK_JUMP + 800), 1000);
  assert.equal(jumped.hidden, false);
  const afterJump = drag(jumped, [DOCK_JUMP + 810, DOCK_JUMP + 830, DOCK_JUMP + 860], 1100);
  assert.equal(afterJump.hidden, true);
}

function theAppFollowingAnAnswerNeverCountsAsAsking(): void {
  let state = settled(200);
  let now = 1000;
  for (let offset = 210; offset <= 400; offset += 10) {
    state = nextDock(state, page(offset), now, false);
    now += 16;
  }
  assert.equal(state.hidden, false);
  // The reader's own move from there still works, measured from where the list is.
  state = drag(state, [410, 420, 440], now);
  assert.equal(state.hidden, true);
}

function offsetsOutsideThePageAreClamped(): void {
  const state = nextDock(settled(200), page(-40), 1000);
  assert.equal(state.hidden, false);
  assert.equal(state.last, 0);
  const past = nextDock(settled(200), page(LONG + 500), 1000);
  assert.equal(past.last, LONG - VIEWPORT);
}

aShortPageNeverHidesTheBar();
movingDownPastTheThresholdHidesIt();
theFirstMoveBackUpBringsItBack();
aTurnResetsHowFarTheReaderHasTravelled();
theTopOfAPageAlwaysShowsIt();
aToggleHoldsWhileTheBarMoves();
aLayoutChangeIsNotAScroll();
aJumpTheAppMadeIsNotTheReader();
theAppFollowingAnAnswerNeverCountsAsAsking();
offsetsOutsideThePageAreClamped();
process.stdout.write('Dock checks passed.\n');
