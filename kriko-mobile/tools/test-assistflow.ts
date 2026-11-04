import assert from 'node:assert/strict';
import { queueAssistantScan } from '../src/engine/assistflow';

async function main() {
  const events: string[] = [];
  const controller = new AbortController();
  assert.equal(await queueAssistantScan({
    signal: controller.signal,
    read: async () => { events.push('read'); return 'observed product'; },
    keep: async () => { events.push('thumbnail'); return 'file://saved'; },
    enqueue: (reading, image) => { assert.equal(reading, 'observed product'); assert.equal(image, 'file://saved'); events.push('queue'); },
  }), true);
  assert.deepEqual(events, ['read', 'thumbnail', 'queue']);
  let enqueued = false;
  assert.equal(await queueAssistantScan({
    signal: controller.signal,
    read: async () => { controller.abort(); return 'late read'; },
    keep: async () => { throw new Error('Cancelled scan must not retain an image'); },
    enqueue: () => { enqueued = true; },
  }), false);
  assert.equal(enqueued, false);
  const cancelledDuringKeep = new AbortController();
  assert.equal(await queueAssistantScan({
    signal: cancelledDuringKeep.signal,
    read: async () => 'product',
    keep: async () => { cancelledDuringKeep.abort(); return undefined; },
    enqueue: () => { enqueued = true; },
  }), false);
  assert.equal(enqueued, false);
  await assert.rejects(queueAssistantScan({
    signal: new AbortController().signal,
    read: async () => { throw new Error('Vision unavailable'); },
    keep: async () => undefined,
    enqueue: () => { enqueued = true; },
  }), /Vision unavailable/);
  assert.equal(enqueued, false);
  console.log('Assistant queue handoff checks passed.');
}
void main();
