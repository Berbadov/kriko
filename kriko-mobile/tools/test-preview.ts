/** The one-line preview of an answer written in Markdown. */

import assert from 'node:assert/strict';

import { plainPreview } from '../src/engine/preview';

function headingMarksAndBulletsAreDropped(): void {
  assert.equal(plainPreview('## Fifth generation Prius – known issues\n\n- Door key leak'),
    'Fifth generation Prius – known issues Door key leak');
  assert.equal(plainPreview('1. First\n2) Second'), 'First Second');
}

function emphasisLinksAndCitationsReadAsPlainWords(): void {
  assert.equal(plainPreview('The **hybrid** battery is `12 V` [1][2], see [recall](https://example.com/x).'),
    'The hybrid battery is 12 V , see recall.');
  assert.equal(plainPreview('Checked in [1, 3] and [4]'), 'Checked in and');
}

function snake_case_words_and_decimals_keep_their_characters(): void {
  // Underscores inside a word are not emphasis; the preview only has to be
  // readable, so stripping them is acceptable, but the words must survive.
  assert.match(plainPreview('model_year 2023 costs 4.5 k'), /model.?year 2023 costs 4\.5 k/);
}

function anEmptyAnswerIsEmpty(): void {
  assert.equal(plainPreview(''), '');
  assert.equal(plainPreview('  \n\n  '), '');
}

headingMarksAndBulletsAreDropped();
emphasisLinksAndCitationsReadAsPlainWords();
snake_case_words_and_decimals_keep_their_characters();
anEmptyAnswerIsEmpty();
console.log('Preview checks passed.');
