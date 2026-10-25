import assert from 'node:assert/strict';
import { normalizeReading } from '../src/engine/reading';

import { restoreScanThreads, withoutScanThreads } from '../src/engine/types';
import type { QueueJob, Thread } from '../src/engine/types';

const reading = {
  brand: 'Acme', product: 'Widget', model: 'W-10', price: '$20', condition: 'used', detail: '', note: '',
};
const job: QueueJob = {
  id: 'scan-1', question: 'Should I buy it?', reading, status: 'done', text: 'Check the battery.',
  sources: [{ n: 1, url: 'https://example.com', title: 'Review', host: 'example.com' }],
  steps: [{ id: 'step-1', kind: 'search', text: 'Searched', at: 20 }],
  threadId: 'thread-1', answerId: 'answer-1', createdAt: 10, updatedAt: 30,
};

function restoresACompletedScanWhenItsThreadWasNotPersisted(): void {
  const threads = restoreScanThreads([], [job]);
  assert.equal(threads.length, 1);
  assert.equal(threads[0].id, 'thread-1');
  assert.equal(threads[0].title, 'Acme Widget W-10');
  assert.equal(threads[0].messages[1].text, 'Check the battery.');
  assert.equal(threads[0].messages[1].steps?.[0].id, 'step-1');
  assert.equal(threads[0].messages[1].sources?.[0].url, 'https://example.com');
}

function reconcilesTheDurableQueueIntoAnOlderThreadSnapshot(): void {
  const stale: Thread = {
    id: 'thread-1', title: 'Product scan', createdAt: Number.NaN, updatedAt: Number.NaN,
    messages: [
      { id: 'user-1', role: 'user', text: job.question, createdAt: 10 },
      { id: 'answer-1', role: 'assistant', text: 'partial', createdAt: 11, pending: true },
    ],
  };
  const [thread] = restoreScanThreads([stale], [job]);
  assert.equal(thread.messages[1].text, job.text);
  assert.equal(thread.messages[1].pending, false);
  assert.equal(thread.messages[1].steps?.length, 1);
  assert.ok(Number.isFinite(thread.updatedAt));
}

function leavesUnlinkedAccessErrorsVisibleOnlyInTheQueue(): void {
  const unlinked = { ...job, threadId: undefined };
  assert.deepEqual(restoreScanThreads([], [unlinked]), []);
}

function deletingAChatRemovesItsScanRecordSoHydrationCannotResurrectIt(): void {
  const remaining = withoutScanThreads([job], new Set(['thread-1']));
  assert.deepEqual(remaining, []);
  assert.deepEqual(restoreScanThreads([], remaining), []);
  assert.deepEqual(withoutScanThreads([job], new Set(['another-thread'])), [job]);
}

function recoversAppearanceOnlyScansWithTheirVisualIdentity(): void {
  const visual = normalizeReading({ brand: '', product: '', model: '', detail: '', price: '', condition: 'unknown', note: '', identityBasis: 'appearance', visualDescription: 'A compact fabric speaker.', visualCandidates: [{ name: 'Portable speaker family', confidence: 'medium', reason: 'Fabric shell and top controls.' }] });
  assert.ok(visual);
  const [thread] = restoreScanThreads([], [{ ...job, reading: visual }]);
  assert.equal(thread.title, 'Possible: Portable speaker family');
  assert.equal(thread.messages[0].reading?.visualDescription, 'A compact fabric speaker.');
  assert.equal(thread.messages[0].reading?.visualCandidates?.[0].confidence, 'medium');
}

recoversAppearanceOnlyScansWithTheirVisualIdentity();
restoresACompletedScanWhenItsThreadWasNotPersisted();
reconcilesTheDurableQueueIntoAnOlderThreadSnapshot();
leavesUnlinkedAccessErrorsVisibleOnlyInTheQueue();
deletingAChatRemovesItsScanRecordSoHydrationCannotResurrectIt();
process.stdout.write('Scan history recovery checks passed.\n');
