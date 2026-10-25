import assert from 'node:assert/strict';

import { drainQueue } from '../src/engine/queue';

interface Job { id: string; status: string }

async function enqueueDoesNotExecuteOrCharge(): Promise<void> {
  const jobs: Job[] = [];
  let charges = 0;
  const enqueue = (id: string) => jobs.push({ id, status: 'queued' });
  const execute = async () => { charges += 1; };

  enqueue('first');
  assert.equal(charges, 0, 'adding a scan to the queue must not debit trial access');
  await drainQueue(jobs, execute);
  assert.equal(charges, 1, 'a charge is made when the worker begins the scan');
}

async function jobsRunSeriallyAndOneFailureDoesNotBlockTheNext(): Promise<void> {
  const order: string[] = [];
  await drainQueue(
    [{ id: 'first', status: 'queued' }, { id: 'second', status: 'queued' }],
    async (job) => {
      order.push(`start:${job.id}`);
      await Promise.resolve();
      if (job.id === 'first') throw new Error('offline provider');
      order.push(`done:${job.id}`);
    },
  );
  assert.deepEqual(order, ['start:first', 'start:second', 'done:second']);
}

async function cancelledAndNonQueuedJobsAreSkipped(): Promise<void> {
  const executed: string[] = [];
  await drainQueue(
    [
      { id: 'cancelled', status: 'queued' },
      { id: 'already-running', status: 'running' },
      { id: 'ready', status: 'queued' },
    ],
    async (job) => { executed.push(job.id); },
    (id) => id === 'cancelled',
  );
  assert.deepEqual(executed, ['ready']);
}

async function main(): Promise<void> {
  await enqueueDoesNotExecuteOrCharge();
  await jobsRunSeriallyAndOneFailureDoesNotBlockTheNext();
  await cancelledAndNonQueuedJobsAreSkipped();
  process.stdout.write('Queued scan checks passed.\n');
}

void main().catch((error: unknown) => {
  process.stderr.write(`${error instanceof Error ? error.stack : String(error)}\n`);
  process.exitCode = 1;
});
