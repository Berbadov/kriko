import assert from 'node:assert/strict';

import { ProviderError, readListing, RequestAborted } from '../src/engine/providers';

const originalFetch = globalThis.fetch;
const validJson = JSON.stringify({
  brand: 'Acme', product: 'Widget', model: 'W-10', price: '$20', condition: 'new',
  detail: 'Black, 128 GB', site: '', url: '', note: '',
});

function response(content: string): Response {
  return new Response(JSON.stringify({ choices: [{ message: { content } }] }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

async function retriesMalformedJsonWithTheSameOriginalDetailImage(): Promise<void> {
  const calls: Record<string, any>[] = [];
  globalThis.fetch = (async (_url: string | URL | Request, init?: RequestInit) => {
    calls.push(JSON.parse(String(init?.body)) as Record<string, any>);
    return response(calls.length === 1 ? 'not json' : validJson);
  }) as typeof fetch;
  try {
    const reading = await readListing('A'.repeat(300), 'image/jpeg', 'deepseek-key');
    assert.equal(reading.model, 'W-10');
    assert.equal(calls.length, 2);
    const image0 = calls[0].messages[0].content[1].image_url;
    const image1 = calls[1].messages[0].content[1].image_url;
    assert.equal(image0.detail, 'original');
    assert.equal(image0.url, image1.url);
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function acceptsPartialStringFieldsWithoutRetrying(): Promise<void> {
  let calls = 0;
  globalThis.fetch = (async () => {
    calls += 1;
    return response(JSON.stringify({ brand: 'TCL', model: '55V6C' }));
  }) as typeof fetch;
  try {
    const reading = await readListing('A'.repeat(300), 'image/jpeg', 'deepseek-key');
    assert.equal(calls, 1, 'omitted optional JSON strings must not trigger a retry');
    assert.equal(reading.brand, 'TCL');
    assert.equal(reading.model, '55V6C');
    assert.equal(reading.product, '');
    assert.equal(reading.site, undefined);
    assert.equal(reading.url, undefined);
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function retriesKnownFieldsWithWrongTypes(): Promise<void> {
  let calls = 0;
  globalThis.fetch = (async () => {
    calls += 1;
    return response(calls === 1
      ? JSON.stringify({ brand: { guess: 'TCL' }, model: '55V6C' })
      : validJson);
  }) as typeof fetch;
  try {
    const reading = await readListing('A'.repeat(300), 'image/jpeg', 'deepseek-key');
    assert.equal(calls, 2);
    assert.equal(reading.brand, 'Acme');
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function emptyKeysAndIncompleteImagesFailBeforeNetwork(): Promise<void> {
  let calls = 0;
  globalThis.fetch = (async () => { calls += 1; return response(validJson); }) as typeof fetch;
  try {
    await assert.rejects(readListing('A'.repeat(300), 'image/jpeg', ' '), /No DeepSeek image-reading key/);
    await assert.rejects(readListing('too small', 'image/jpeg', 'deepseek-key'), /screenshot data is incomplete/);
    assert.equal(calls, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function cancellationPreventsMalformedReplyRetry(): Promise<void> {
  const controller = new AbortController();
  let calls = 0;
  globalThis.fetch = (async () => {
    calls += 1;
    controller.abort();
    return response('not json');
  }) as typeof fetch;
  try {
    await assert.rejects(
      readListing('A'.repeat(300), 'image/jpeg', 'deepseek-key', controller.signal),
      (error: unknown) => error instanceof RequestAborted,
    );
    assert.equal(calls, 1);
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function repeatedMalformedRepliesGiveAnActionableFailure(): Promise<void> {
  let calls = 0;
  globalThis.fetch = (async () => { calls += 1; return response('{}'); }) as typeof fetch;
  try {
    await assert.rejects(
      readListing('A'.repeat(300), 'image/jpeg', 'deepseek-key'),
      (error: unknown) => error instanceof ProviderError && /enter the product details by hand/.test(error.message),
    );
    assert.equal(calls, 2);
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function main(): Promise<void> {
  await retriesMalformedJsonWithTheSameOriginalDetailImage();
  await acceptsPartialStringFieldsWithoutRetrying();
  await retriesKnownFieldsWithWrongTypes();
  await emptyKeysAndIncompleteImagesFailBeforeNetwork();
  await cancellationPreventsMalformedReplyRetry();
  await repeatedMalformedRepliesGiveAnActionableFailure();
  process.stdout.write('Vision reader checks passed.\n');
}

void main().catch((error: unknown) => {
  process.stderr.write(`${error instanceof Error ? error.stack : String(error)}\n`);
  process.exitCode = 1;
});
