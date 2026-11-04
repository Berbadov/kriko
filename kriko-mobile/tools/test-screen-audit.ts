import assert from 'node:assert/strict';
import { createAuditTransactions, type AuditStorage } from '../src/engine/screenAuditCore';

interface Entry { id: string; status: string; at: number }

class MemoryStorage implements AuditStorage {
  data: string | null = null;
  failNextWrite = false;
  holdRead: Promise<void> | null = null;
  readStarted: (() => void) | null = null;
  async getItem(): Promise<string | null> {
    this.readStarted?.();
    if (this.holdRead) await this.holdRead;
    return this.data;
  }
  async setItem(_key: string, value: string): Promise<void> {
    if (this.failNextWrite) { this.failNextWrite = false; throw new Error('disk unavailable'); }
    this.data = value;
  }
}

async function concurrentWritesDoNotLoseRowsAndStayBounded(): Promise<void> {
  const storage = new MemoryStorage();
  const audit = createAuditTransactions<Entry>(storage, 'audit', 50);
  await Promise.all(Array.from({ length: 65 }, (_, index) => audit.begin({ id: `r${index}`, at: index, status: 'reading' })));
  const entries = await audit.load();
  assert.equal(entries.length, 50);
  assert.equal(entries.at(-1)?.id, 'r64');
  assert.equal(new Set(entries.map((entry) => entry.id)).size, 50);
}

async function failedWritesRejectOnceAndDoNotPoisonQueue(): Promise<void> {
  const storage = new MemoryStorage();
  const audit = createAuditTransactions<Entry>(storage, 'audit', 50);
  storage.failNextWrite = true;
  await assert.rejects(audit.begin({ id: 'failed', at: 1, status: 'reading' }), /disk unavailable/);
  const epoch = await audit.begin({ id: 'saved', at: 2, status: 'reading' });
  assert.notEqual(epoch, null);
  assert.deepEqual(await audit.load(), [{ id: 'saved', at: 2, status: 'reading' }]);
}

async function aReadInFlightDuringClearCannotRecreateItsEntry(): Promise<void> {
  const storage = new MemoryStorage();
  let releaseRead!: () => void;
  storage.holdRead = new Promise<void>((resolve) => { releaseRead = resolve; });
  const readStarted = new Promise<void>((resolve) => { storage.readStarted = resolve; });
  const audit = createAuditTransactions<Entry>(storage, 'audit', 50);
  const begin = audit.begin({ id: 'late', at: 1, status: 'reading' });
  await readStarted;
  const clear = audit.clear();
  releaseRead();
  assert.equal(await begin, null);
  await clear;
  assert.deepEqual(await audit.load(), []);
}

async function finishFromBeforeClearCannotResurrectTheLog(): Promise<void> {
  const storage = new MemoryStorage();
  const audit = createAuditTransactions<Entry>(storage, 'audit', 50);
  const epoch = await audit.begin({ id: 'old', at: 1, status: 'reading' });
  assert.notEqual(epoch, null);
  await audit.clear();
  assert.equal(await audit.finish('old', { status: 'success' }, epoch as number), false);
  assert.deepEqual(await audit.load(), []);
}

async function finishingAnEntryThatWasRemovedReturnsFalse(): Promise<void> {
  const storage = new MemoryStorage();
  const audit = createAuditTransactions<Entry>(storage, 'audit', 1);
  const epoch = await audit.begin({ id: 'evicted', at: 1, status: 'reading' });
  assert.notEqual(epoch, null);
  await audit.begin({ id: 'kept', at: 2, status: 'reading' });
  assert.equal(await audit.finish('evicted', { status: 'success' }, epoch as number), false);
}

async function main(): Promise<void> {
  await concurrentWritesDoNotLoseRowsAndStayBounded();
  await failedWritesRejectOnceAndDoNotPoisonQueue();
  await aReadInFlightDuringClearCannotRecreateItsEntry();
  await finishFromBeforeClearCannotResurrectTheLog();
  await finishingAnEntryThatWasRemovedReturnsFalse();
  process.stdout.write('Screen audit checks passed.\n');
}

main().catch((error) => { console.error(error); process.exit(1); });
