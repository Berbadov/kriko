/**
 * The folder of chat pictures only ever holds what a chat or a scan refers to.
 * The rule is pure, so a wrong delete is caught here and not on a reader's phone.
 */

import assert from 'node:assert/strict';

import { orphanedThumbnails } from '../src/engine/thumbrules';

const folder = 'file:///data/user/0/app/files/scans/';

function keepsEverythingAChatRefersTo(): void {
  const names = ['a.jpg', 'b.jpg'];
  assert.deepEqual(orphanedThumbnails(names, [`${folder}a.jpg`, `${folder}b.jpg`], folder), []);
}

function deletesOnlyWhatNothingRefersTo(): void {
  const names = ['a.jpg', 'b.jpg', 'c.jpg'];
  assert.deepEqual(orphanedThumbnails(names, [`${folder}b.jpg`, undefined], folder), ['a.jpg', 'c.jpg']);
}

function aPictureFromElsewhereProtectsNothingHere(): void {
  // A picked photo still living in the cache is not this folder's to keep or lose.
  const names = ['a.jpg'];
  assert.deepEqual(orphanedThumbnails(names, ['file:///cache/ImageManipulator/a.jpg'], folder), ['a.jpg']);
}

function anEmptyFolderHasNothingToDelete(): void {
  assert.deepEqual(orphanedThumbnails([], [`${folder}a.jpg`], folder), []);
}

keepsEverythingAChatRefersTo();
deletesOnlyWhatNothingRefersTo();
aPictureFromElsewhereProtectsNothingHere();
anEmptyFolderHasNothingToDelete();
process.stdout.write('Chat picture folder checks passed.\n');
