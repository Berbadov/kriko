/**
 * The thumb-side scroll rail: when it appears, where the handle sits for a
 * scroll position, and which position a handle stands for.
 */

import assert from 'node:assert/strict';

import {
  SCRUB_HANDLE_H,
  SCRUB_MIN_RATIO,
  clampHandleTop,
  handleTopFor,
  handleTravel,
  offsetForHandleTop,
  percentThrough,
  railHeight,
  scrubEligible,
} from '../src/engine/scrubrules';

const VIEWPORT = 700;

function theRailAppearsOnlyForALongConversation(): void {
  assert.equal(scrubEligible(VIEWPORT, VIEWPORT), false);
  assert.equal(scrubEligible(VIEWPORT * SCRUB_MIN_RATIO - 1, VIEWPORT), false);
  assert.equal(scrubEligible(VIEWPORT * SCRUB_MIN_RATIO, VIEWPORT), true);
  // Nothing measured yet.
  assert.equal(scrubEligible(5000, 0), false);
}

function theRailStaysWithinReachOfAThumb(): void {
  assert.equal(railHeight(200), 140);
  assert.equal(railHeight(700), 300);
  assert.equal(railHeight(2000), 300);
  assert.equal(railHeight(500), 250);
}

function theHandleSitsAtTheEndsOfItsTravel(): void {
  const content = 4000;
  const rail = 250;
  const travel = handleTravel(rail);
  assert.equal(travel, rail - SCRUB_HANDLE_H);
  assert.equal(handleTopFor(0, content, VIEWPORT, rail), 0);
  assert.equal(handleTopFor(content - VIEWPORT, content, VIEWPORT, rail), travel);
  assert.equal(handleTopFor((content - VIEWPORT) / 2, content, VIEWPORT, rail), travel / 2);
}

function aPositionOutsideTheContentIsClamped(): void {
  const content = 4000;
  const rail = 250;
  assert.equal(handleTopFor(-300, content, VIEWPORT, rail), 0);
  assert.equal(handleTopFor(content * 2, content, VIEWPORT, rail), handleTravel(rail));
  assert.equal(offsetForHandleTop(-20, content, VIEWPORT, rail), 0);
  assert.equal(offsetForHandleTop(rail * 3, content, VIEWPORT, rail), content - VIEWPORT);
  assert.equal(clampHandleTop(-5, rail), 0);
  assert.equal(clampHandleTop(999, rail), handleTravel(rail));
}

function theHandleAndTheOffsetAreEachOthersInverse(): void {
  const content = 9000;
  const rail = 280;
  for (const offset of [0, 120, 1500, 4321, content - VIEWPORT]) {
    const top = handleTopFor(offset, content, VIEWPORT, rail);
    const back = offsetForHandleTop(top, content, VIEWPORT, rail);
    assert.ok(Math.abs(back - offset) < 1e-6, `${offset} came back as ${back}`);
  }
}

function aListThatDoesNotScrollHasNoTravel(): void {
  assert.equal(handleTopFor(50, 600, VIEWPORT, 250), 0);
  assert.equal(offsetForHandleTop(80, 600, VIEWPORT, 250), 0);
  assert.equal(handleTopFor(50, 4000, VIEWPORT, SCRUB_HANDLE_H), 0);
  assert.equal(offsetForHandleTop(10, 4000, VIEWPORT, SCRUB_HANDLE_H), 0);
}

function theHintReadsAsAWholePercent(): void {
  assert.equal(percentThrough(0, 4000, VIEWPORT), 0);
  assert.equal(percentThrough(3300, 4000, VIEWPORT), 100);
  assert.equal(percentThrough(1650, 4000, VIEWPORT), 50);
  assert.equal(percentThrough(-10, 4000, VIEWPORT), 0);
  assert.equal(percentThrough(10, 500, VIEWPORT), 0);
}

theRailAppearsOnlyForALongConversation();
theRailStaysWithinReachOfAThumb();
theHandleSitsAtTheEndsOfItsTravel();
aPositionOutsideTheContentIsClamped();
theHandleAndTheOffsetAreEachOthersInverse();
aListThatDoesNotScrollHasNoTravel();
theHintReadsAsAWholePercent();
process.stdout.write('Scroll rail checks passed.\n');
