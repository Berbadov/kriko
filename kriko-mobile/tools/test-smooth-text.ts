/**
 * A streamed answer is shown at a steady pace: never ahead of the stream, never
 * far behind it, always between words, and never as half-written Markdown.
 */

import assert from 'node:assert/strict';

import {
  REVEAL_MAX_STEP_MS,
  advance,
  closeOpen,
  revealEnd,
  visibleText,
} from '../src/engine/smoothtext';

/** Run the pace for `ms` and return how much is shown. */
function run(total: number, ms: number, draining = false, from = 0): number {
  let shown = from;
  for (let at = 0; at < ms; at += 16) shown = advance(shown, total, 16, draining);
  return shown;
}

function theReaderNeverGetsAheadOfTheStream(): void {
  assert.equal(advance(0, 0, 16, false), 0);
  assert.equal(advance(50, 50, 16, false), 50);
  assert.ok(advance(10, 12, 64, true) <= 12);
  for (const total of [1, 30, 400, 9000]) assert.ok(run(total, 5000) <= total);
}

function aSmallBacklogStillFinishes(): void {
  assert.equal(run(6, 400), 6);
}

function aBigBacklogCatchesUpFast(): void {
  const shown = run(1500, 1500);
  assert.ok(shown > 1300, `after 1.5 s only ${shown} of 1500 were shown`);
}

function aFinishedAnswerDrainsFasterThanARunningOne(): void {
  assert.ok(run(600, 200, true) > run(600, 200, false));
  assert.equal(run(600, 1200, true), 600);
}

function theBacklogStaysSmallAgainstASteadyStream(): void {
  // 200 characters a second arrives; the reader should trail by well under a second of it.
  let shown = 0;
  let total = 0;
  for (let at = 0; at < 6000; at += 16) {
    total += 3.2;
    shown = advance(shown, total, 16, false);
  }
  assert.ok(total - shown < 120, `the reader trails by ${Math.round(total - shown)} characters`);
}

function aStalledFrameIsNotACatchUpJump(): void {
  assert.ok(REVEAL_MAX_STEP_MS <= 100);
}

function theCutLandsBetweenWords(): void {
  const text = 'The earbuds pair with one phone at a time.';
  assert.equal(text.slice(0, revealEnd(text, 9, false)), 'The');
  assert.equal(text.slice(0, revealEnd(text, 11, false)), 'The earbuds');
  // On the space after a word: the space waits for the next word.
  assert.equal(revealEnd(text, 4, false), 3);
  assert.equal(revealEnd(text, 0, false), 0);
  // The whole text, when the pace has reached the end.
  assert.equal(revealEnd(text, 999, false), text.length);
  assert.equal(revealEnd(text, 999, true), text.length);
}

function aLongLinkMayBeCutInside(): void {
  const text = `See ${'x'.repeat(60)}`;
  assert.equal(revealEnd(text, 40, false), 40);
}

function aFinishedAnswerIsDrawnWhole(): void {
  const text = 'Check the **hinge** first.';
  assert.equal(revealEnd(text, text.length, true), text.length);
  assert.equal(visibleText(text, text.length, true), text);
  // Still draining: a prefix, closed, exactly like a running answer.
  assert.equal(visibleText(text, 17, false), 'Check the **hinge**');
  assert.equal(visibleText(text, 17, true), 'Check the **hinge**');
}

function boldThatHasNotClosedIsClosedNotShownAsSymbols(): void {
  const text = 'Check the **hinge and the cable** first.';
  const partial = text.slice(0, revealEnd(text, 22, false));
  assert.equal(partial, 'Check the **hinge and');
  assert.equal(closeOpen(partial), 'Check the **hinge and**');
  // Just an opener: held back, not drawn as stars.
  assert.equal(text.slice(0, revealEnd(text, 12, false)), 'Check the');
}

function codeThatHasNotClosedIsClosed(): void {
  assert.equal(closeOpen('Use `SM-R510'), 'Use `SM-R510`');
  assert.equal(closeOpen('Use `SM-R510` now'), 'Use `SM-R510` now');
  assert.equal(closeOpen('**bold `code'), '**bold `code`**');
}

function aCitationIsDrawnWholeOrNotAtAll(): void {
  const text = 'It cracks near the hinge [12] on older units.';
  assert.equal(text.slice(0, revealEnd(text, 28, false)), 'It cracks near the hinge');
  assert.equal(text.slice(0, revealEnd(text, 29, false)), 'It cracks near the hinge [12]');
}

function anUnfinishedLinkIsHeldBack(): void {
  const text = 'Read [the report](https://example.com/report) first.';
  assert.equal(text.slice(0, revealEnd(text, 30, false)), 'Read');
  assert.equal(text.slice(0, revealEnd(text, 46, false)), 'Read [the report](https://example.com/report)');
}

function aStrayBracketDoesNotFreezeTheAnswer(): void {
  const text = `Index [0 ${'and then a very long sentence with no closing bracket at all. '.repeat(4)}`;
  const end = revealEnd(text, text.length - 3, false);
  assert.ok(end > 150, `the reveal froze at ${end}`);
}

function aBlockMarkerAloneIsHeldBackUntilItHasWords(): void {
  const text = 'Before.\n- Check the hinge\n- Then the cable';
  assert.equal(text.slice(0, revealEnd(text, 10, false)), 'Before.');
  assert.equal(text.slice(0, revealEnd(text, 20, false)), 'Before.\n- Check the');
  const numbered = '1. Open it';
  assert.equal(numbered.slice(0, revealEnd(numbered, 2, false)), '');
  const heading = 'Intro\n## Verdict';
  assert.equal(heading.slice(0, revealEnd(heading, 9, false)), 'Intro');
}

theReaderNeverGetsAheadOfTheStream();
aSmallBacklogStillFinishes();
aBigBacklogCatchesUpFast();
aFinishedAnswerDrainsFasterThanARunningOne();
theBacklogStaysSmallAgainstASteadyStream();
aStalledFrameIsNotACatchUpJump();
theCutLandsBetweenWords();
aLongLinkMayBeCutInside();
aFinishedAnswerIsDrawnWhole();
boldThatHasNotClosedIsClosedNotShownAsSymbols();
codeThatHasNotClosedIsClosed();
aCitationIsDrawnWholeOrNotAtAll();
anUnfinishedLinkIsHeldBack();
aStrayBracketDoesNotFreezeTheAnswer();
aBlockMarkerAloneIsHeldBackUntilItHasWords();
process.stdout.write('Smooth text checks passed.\n');
