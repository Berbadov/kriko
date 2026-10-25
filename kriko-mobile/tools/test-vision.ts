import assert from 'node:assert/strict';

import { readingTitle, turnBrief } from '../src/engine/prompt';
import { hasProductReading, normalizeReading } from '../src/engine/reading';
import { ProviderError, readListing, RequestAborted, VISION_MODEL } from '../src/engine/providers';

const originalFetch = globalThis.fetch;
const IMAGE = 'A'.repeat(300);
const DETAIL = 'B'.repeat(300);
const validJson = JSON.stringify({
  brand: 'Acme', product: 'Widget', model: 'W-10', price: '$20', condition: 'new',
  detail: 'Black, 128 GB', site: '', url: '', note: '',
});

function response(content: string, finish = 'stop'): Response {
  return new Response(JSON.stringify({
    choices: [{ message: { content }, finish_reason: finish }],
  }), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });
}

function requestBody(init?: RequestInit): Record<string, any> {
  return JSON.parse(String(init?.body)) as Record<string, any>;
}

async function sendsTheReasoningFreeJsonRequest(): Promise<void> {
  const calls: Record<string, any>[] = [];
  globalThis.fetch = (async (_url: string | URL | Request, init?: RequestInit) => {
    calls.push(requestBody(init));
    return response(validJson);
  }) as typeof fetch;
  try {
    const reading = await readListing(IMAGE, 'image/jpeg', 'deepseek-key');
    assert.equal(reading.model, 'W-10');
    assert.equal(calls.length, 1);
    assert.equal(calls[0].model, VISION_MODEL);
    assert.equal(calls[0].stream, false);
    assert.equal(calls[0].reasoning_effort, 'none');
    assert.deepEqual(calls[0].response_format, { type: 'json_object' });
    assert.equal(calls[0].temperature, 0.1);
    assert.equal(calls[0].max_tokens, 5000);
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function sendsTheDetailImageOnlyWhenProvided(): Promise<void> {
  const calls: Record<string, any>[] = [];
  globalThis.fetch = (async (_url: string | URL | Request, init?: RequestInit) => {
    calls.push(requestBody(init));
    return response(validJson);
  }) as typeof fetch;
  try {
    await readListing(IMAGE, 'image/jpeg', 'deepseek-key');
    await readListing(IMAGE, 'image/jpeg', 'deepseek-key', undefined, DETAIL);
    const plain = calls[0].messages[0].content as Record<string, any>[];
    const cropped = calls[1].messages[0].content as Record<string, any>[];
    const images = (parts: Record<string, any>[]) => parts.filter((part) => part.type === 'image_url');
    assert.equal(calls.length, 2);
    assert.equal(images(plain).length, 1, 'a scan with no crop must send only the full image');
    assert.equal(images(cropped).length, 2, 'a crop must ride beside the full image');
    assert.equal(plain[0].text.includes('tight crop'), false);
    assert.match(cropped[0].text, /tight crop/);
    assert.match(cropped[0].text, /authoritative for label and model-code text/);
    assert.equal(images(cropped)[0].image_url.url, `data:image/jpeg;base64,${IMAGE}`);
    assert.equal(images(cropped)[1].image_url.url, `data:image/jpeg;base64,${DETAIL}`);
    assert.equal(images(cropped)[1].image_url.detail, 'original');
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function anEmptyReplyAtLengthRetriesThenFailsActionably(): Promise<void> {
  let calls = 0;
  globalThis.fetch = (async () => {
    calls += 1;
    return response('', 'length');
  }) as typeof fetch;
  try {
    await assert.rejects(
      readListing(IMAGE, 'image/jpeg', 'deepseek-key'),
      (error: unknown) => error instanceof ProviderError
        && /ran out of room/.test(error.message)
        && /enter the product details by hand/.test(error.message),
    );
    assert.equal(calls, 2, 'an empty reply must be retried once before failing');
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function coercesNumbersAndBooleansInsteadOfRejecting(): Promise<void> {
  globalThis.fetch = (async () => response(JSON.stringify({
    product: 'Drill', price: 249.9, model: 550, note: true,
  }))) as typeof fetch;
  try {
    const reading = await readListing(IMAGE, 'image/jpeg', 'deepseek-key');
    assert.equal(reading.price, '249.9');
    assert.equal(reading.model, '550');
    assert.equal(reading.note, 'true');
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function acceptsDocumentedFieldAliases(): Promise<void> {
  const cases: Array<[string, string, keyof ReadingShape, string?]> = [
    ['brand', 'Ridgid', 'brand'],
    ['brandName', 'Ridgid', 'brand'],
    ['brand_name', 'Ridgid', 'brand'],
    ['manufacturer', 'Ridgid', 'brand'],
    ['title', 'Cordless drill', 'product'],
    ['name', 'Cordless drill', 'product'],
    ['model_number', 'R-18', 'model'],
    ['modelNumber', 'R-18', 'model'],
    ['part_number', 'R-18', 'model'],
    ['partNumber', 'R-18', 'model'],
    ['asking_price', '99 EUR', 'price'],
    ['price_text', '99 EUR', 'price'],
    ['visual_description', 'A green drill body.', 'visualDescription'],
    ['visualDescription', 'A green drill body.', 'visualDescription'],
    ['identityBasis', 'text', 'identityBasis', 'Cordless drill'],
    ['identity_basis', 'text', 'identityBasis', 'Cordless drill'],
  ];
  for (const [key, value, expected, alsoProduct] of cases) {
    globalThis.fetch = (async () => response(JSON.stringify({
      [key]: value,
      ...(alsoProduct ? { product: alsoProduct } : {}),
    }))) as typeof fetch;
    try {
      const reading = await readListing(IMAGE, 'image/jpeg', 'deepseek-key');
      assert.equal(reading[expected], value, `alias ${key}`);
    } finally {
      globalThis.fetch = originalFetch;
    }
  }
}

type ReadingShape = {
  brand: string;
  product: string;
  model: string;
  price: string;
  visualDescription?: string;
  identityBasis?: string;
};

async function acceptsAlternateNamesForEveryField(): Promise<void> {
  globalThis.fetch = (async () => response(JSON.stringify({
    brandName: 'Bosch',
    name: 'Impact driver',
    model_number: 'GDX 18V-200',
    price_text: '149 EUR',
  }))) as typeof fetch;
  try {
    const reading = await readListing(IMAGE, 'image/jpeg', 'deepseek-key');
    assert.equal(reading.brand, 'Bosch');
    assert.equal(reading.product, 'Impact driver');
    assert.equal(reading.model, 'GDX 18V-200');
    assert.equal(reading.price, '149 EUR');
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function acceptsEveryCandidateListAlias(): Promise<void> {
  for (const key of ['visualCandidates', 'candidates', 'matches', 'possible_matches']) {
    globalThis.fetch = (async () => response(JSON.stringify({
      visualDescription: 'A rectangular label printer with a top lid.',
      identityBasis: 'appearance',
      [key]: [{ name: 'Desktop label printer', confidence: 'HIGH', reason: 'Lid and control layout.' }],
    }))) as typeof fetch;
    try {
      const reading = await readListing(IMAGE, 'image/jpeg', 'deepseek-key');
      assert.equal(reading.visualCandidates?.[0]?.name, 'Desktop label printer', `candidate alias ${key}`);
      assert.equal(reading.visualCandidates?.[0]?.confidence, 'high', `candidate confidence ${key}`);
    } finally {
      globalThis.fetch = originalFetch;
    }
  }
}

async function salvagesAFencedObjectWithTrailingCommas(): Promise<void> {
  globalThis.fetch = (async () => response('```json\n{"brand":"Acme","product":"Widget","model":"W-10",}\n```')) as typeof fetch;
  try {
    const reading = await readListing(IMAGE, 'image/jpeg', 'deepseek-key');
    assert.equal(reading.brand, 'Acme');
    assert.equal(reading.model, 'W-10');
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function salvagesSmartQuotesInsideProse(): Promise<void> {
  const smart = '\uFEFFHere is the reading:\n{\u201Cbrand\u201D: \u201CAcme\u201D, \u201Cproduct\u201D: \u201CWidget\u201D, \u201Cmodel\u201D: \u201CW-10\u201D,}\nThat is all I can see.';
  globalThis.fetch = (async () => response(smart)) as typeof fetch;
  try {
    const reading = await readListing(IMAGE, 'image/jpeg', 'deepseek-key');
    assert.equal(reading.brand, 'Acme');
    assert.equal(reading.product, 'Widget');
    assert.equal(reading.model, 'W-10');
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function findsAnObjectAfterMalformedBraces(): Promise<void> {
  globalThis.fetch = (async () => response('I tried {not json} but the reply is {"brand":"Acme","model":"W-10"}.')) as typeof fetch;
  try {
    const reading = await readListing(IMAGE, 'image/jpeg', 'deepseek-key');
    assert.equal(reading.brand, 'Acme');
    assert.equal(reading.model, 'W-10');
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function turnsAProseReplyIntoAUsableReading(): Promise<void> {
  let calls = 0;
  const prose = 'Compact cordless drill with a black rubber grip.\nThe battery label is turned away, so the exact model is not visible.';
  globalThis.fetch = (async () => {
    calls += 1;
    return response(prose);
  }) as typeof fetch;
  try {
    const reading = await readListing(IMAGE, 'image/jpeg', 'deepseek-key');
    assert.equal(calls, 1, 'prose must not be retried as a failed JSON reply');
    assert.equal(reading.product, 'Compact cordless drill with a black rubber grip.');
    assert.equal(reading.model, '', 'prose can never invent or confirm a model');
    assert.equal(reading.identityBasis, 'unknown');
    assert.match(reading.note, /prose/);
    assert.ok(reading.detail.includes('battery label is turned away'));
    assert.ok(hasProductReading(reading));
    assert.equal(readingTitle(reading), 'Possible: Compact cordless drill with a black rubber grip.');
    assert.match(turnBrief('What is this?', reading), /What the image does not settle/);
    const restored = normalizeReading(JSON.parse(JSON.stringify(reading)));
    assert.equal(restored?.product, reading.product);
    assert.equal(restored?.identityBasis, 'unknown');
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function dropsOnlyAMalformedCandidate(): Promise<void> {
  globalThis.fetch = (async () => response(JSON.stringify({
    visualDescription: 'A camera with a central viewfinder.',
    identityBasis: 'appearance',
    visualCandidates: [
      { name: 'Camera family A', confidence: 'medium', reason: 'Viewfinder shape.' },
      { confidence: 'high', reason: 'No name at all.' },
      'not an object',
      { name: 'Camera family B', confidence: 'low', reason: 'Control placement.' },
    ],
  }))) as typeof fetch;
  try {
    const reading = await readListing(IMAGE, 'image/jpeg', 'deepseek-key');
    assert.deepEqual(reading.visualCandidates?.map((item) => item.name), ['Camera family A', 'Camera family B']);
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function acceptsTurkishIdentityBasisWords(): Promise<void> {
  const cases: Array<[string, 'text' | 'appearance' | 'mixed', boolean]> = [
    ['metin', 'text', false],
    ['GÖRÜNÜM', 'appearance', true],
    ['gorunum', 'appearance', true],
    ['karma', 'mixed', false],
  ];
  for (const [word, expected, modelCleared] of cases) {
    globalThis.fetch = (async () => response(JSON.stringify({
      product: 'Cordless drill', model: 'D-18', identityBasis: word,
      visualDescription: 'Compact body with a black grip.',
    }))) as typeof fetch;
    try {
      const reading = await readListing(IMAGE, 'image/jpeg', 'deepseek-key');
      assert.equal(reading.identityBasis, expected, word);
      assert.equal(reading.model, modelCleared ? '' : 'D-18', word);
    } finally {
      globalThis.fetch = originalFetch;
    }
  }
}

async function retriesMalformedJsonWithTheSameOriginalDetailImage(): Promise<void> {
  const calls: Record<string, any>[] = [];
  globalThis.fetch = (async (_url: string | URL | Request, init?: RequestInit) => {
    calls.push(requestBody(init));
    return response(calls.length === 1 ? 'not json' : validJson);
  }) as typeof fetch;
  try {
    const reading = await readListing(IMAGE, 'image/jpeg', 'deepseek-key');
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
    const reading = await readListing(IMAGE, 'image/jpeg', 'deepseek-key');
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

async function toleratesAnUnusableNestedScalarWithoutRejectingTheReading(): Promise<void> {
  let calls = 0;
  globalThis.fetch = (async () => {
    calls += 1;
    return response(JSON.stringify({ brand: { guess: 'TCL' }, model: '55V6C' }));
  }) as typeof fetch;
  try {
    const reading = await readListing(IMAGE, 'image/jpeg', 'deepseek-key');
    assert.equal(calls, 1, 'one unusable value must not throw away the rest of the reading');
    assert.equal(reading.brand, '');
    assert.equal(reading.model, '55V6C');
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function emptyKeysAndIncompleteImagesFailBeforeNetwork(): Promise<void> {
  let calls = 0;
  globalThis.fetch = (async () => { calls += 1; return response(validJson); }) as typeof fetch;
  try {
    await assert.rejects(readListing(IMAGE, 'image/jpeg', ' '), /No DeepSeek image-reading key/);
    await assert.rejects(readListing('too small', 'image/jpeg', 'deepseek-key'), /screenshot data is incomplete/);
    await assert.rejects(
      readListing(IMAGE, 'image/jpeg', 'deepseek-key', undefined, 'too small'),
      /screenshot data is incomplete/,
    );
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
      readListing(IMAGE, 'image/jpeg', 'deepseek-key', controller.signal),
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
      readListing(IMAGE, 'image/jpeg', 'deepseek-key'),
      (error: unknown) => error instanceof ProviderError && /enter the product details by hand/.test(error.message),
    );
    assert.equal(calls, 2);
  } finally {
    globalThis.fetch = originalFetch;
  }
}

async function identifiesAPhotoWithoutAnyReadableText(): Promise<void> {
  const calls: Record<string, any>[] = [];
  globalThis.fetch = (async (_url: string | URL | Request, init?: RequestInit) => {
    calls.push(requestBody(init));
    return response(JSON.stringify({
      brand: '', product: '', model: '', price: '', condition: 'unknown', detail: '', note: 'The underside label would distinguish similar versions.',
      identityBasis: 'appearance', visualDescription: 'A compact cylindrical speaker, fabric mesh, and a vertical row of rubber buttons.',
      visualCandidates: [{ name: 'Portable fabric Bluetooth speaker', confidence: 'medium', reason: 'Cylindrical body and rubber control strip.' }],
    }));
  }) as typeof fetch;
  try {
    const reading = await readListing(IMAGE, 'image/jpeg', 'deepseek-key');
    assert.equal(calls.length, 1, 'a useful appearance-only result must not be retried as failed OCR');
    assert.equal(reading.detail, '');
    assert.equal(reading.model, '');
    assert.equal(reading.identityBasis, 'appearance');
    assert.equal(reading.visualCandidates?.[0].confidence, 'medium');
    assert.ok(hasProductReading(reading), 'photo-only observations must enable the question flow');
    assert.equal(readingTitle(reading), 'Possible: Portable fabric Bluetooth speaker');
    assert.equal(calls[0].messages[0].content[1].image_url.detail, 'original');
    const brief = turnBrief('What is this and what should I check?', reading);
    assert.ok(brief.includes(reading.visualDescription!));
    assert.ok(brief.includes('Portable fabric Bluetooth speaker'));
    assert.match(brief, /unconfirmed search leads/);
    assert.match(brief, /do not merge evidence/);
    const restored = normalizeReading(JSON.parse(JSON.stringify(reading)));
    assert.deepEqual(restored, reading, 'history restoration must preserve visual clues and uncertainty');
  } finally { globalThis.fetch = originalFetch; }
}

async function anAppearanceGuessCannotBecomeAConfirmedModel(): Promise<void> {
  globalThis.fetch = (async () => response(JSON.stringify({
    product: 'Wireless earbuds', model: 'Buds X2', identityBasis: 'appearance',
    visualDescription: 'Rounded earpieces and a pebble-shaped charging case; no label is visible.',
  }))) as typeof fetch;
  try {
    const reading = await readListing(IMAGE, 'image/jpeg', 'deepseek-key');
    assert.equal(reading.model, '');
    assert.equal(reading.visualCandidates?.[0].name, 'Wireless earbuds Buds X2');
    assert.equal(reading.visualCandidates?.[0].confidence, 'low');
    assert.equal(readingTitle(reading), 'Possible: Wireless earbuds Buds X2');
    assert.match(turnBrief('Which model?', reading), /Model \/ part code: not visible/);
  } finally { globalThis.fetch = originalFetch; }
}

async function boundsCandidatesAndDoesNotPromoteInvalidConfidence(): Promise<void> {
  globalThis.fetch = (async () => response(JSON.stringify({
    visualDescription: 'A camera with a central viewfinder and interchangeable lens.', identityBasis: 'appearance',
    visualCandidates: [
      { name: 'Camera family A', confidence: 100, reason: 'Viewfinder shape.' },
      { name: 'camera family a', confidence: 'high', reason: 'Duplicate.' },
      { name: 'Camera family B', confidence: 'medium', reason: 'Control placement.' },
      { name: 'Camera family C', confidence: 'low', reason: 'Lens mount outline.' },
      { name: 'Camera family D', confidence: 'high', reason: 'Too many guesses.' },
    ],
  }))) as typeof fetch;
  try {
    const reading = await readListing(IMAGE, 'image/jpeg', 'deepseek-key');
    assert.equal(reading.visualCandidates?.length, 3);
    assert.equal(reading.visualCandidates?.[0].confidence, 'low');
    assert.deepEqual(reading.visualCandidates?.map((item) => item.name), ['Camera family A', 'Camera family B', 'Camera family C']);
  } finally { globalThis.fetch = originalFetch; }
}

async function incompleteVisualResultsNeverAcquireConfirmedTitles(): Promise<void> {
  for (const identityBasis of ['appearance', 'unknown'] as const) {
    globalThis.fetch = (async () => response(JSON.stringify({ brand: 'Acme', product: 'Widget W-10', identityBasis }))) as typeof fetch;
    try {
      const reading = await readListing(IMAGE, 'image/jpeg', 'deepseek-key');
      assert.equal(readingTitle(reading), 'Possible: Acme Widget W-10');
      const restored = normalizeReading(JSON.parse(JSON.stringify(reading)));
      assert.ok(restored);
      assert.equal(readingTitle(restored, true), 'Possible: Acme Widget W-10');
    } finally { globalThis.fetch = originalFetch; }
  }
}

async function main(): Promise<void> {
  await sendsTheReasoningFreeJsonRequest();
  await sendsTheDetailImageOnlyWhenProvided();
  await anEmptyReplyAtLengthRetriesThenFailsActionably();
  await coercesNumbersAndBooleansInsteadOfRejecting();
  await acceptsDocumentedFieldAliases();
  await acceptsAlternateNamesForEveryField();
  await acceptsEveryCandidateListAlias();
  await salvagesAFencedObjectWithTrailingCommas();
  await salvagesSmartQuotesInsideProse();
  await findsAnObjectAfterMalformedBraces();
  await turnsAProseReplyIntoAUsableReading();
  await dropsOnlyAMalformedCandidate();
  await acceptsTurkishIdentityBasisWords();
  await incompleteVisualResultsNeverAcquireConfirmedTitles();
  await identifiesAPhotoWithoutAnyReadableText();
  await anAppearanceGuessCannotBecomeAConfirmedModel();
  await boundsCandidatesAndDoesNotPromoteInvalidConfidence();
  await retriesMalformedJsonWithTheSameOriginalDetailImage();
  await acceptsPartialStringFieldsWithoutRetrying();
  await toleratesAnUnusableNestedScalarWithoutRejectingTheReading();
  await emptyKeysAndIncompleteImagesFailBeforeNetwork();
  await cancellationPreventsMalformedReplyRetry();
  await repeatedMalformedRepliesGiveAnActionableFailure();
  process.stdout.write('Vision reader checks passed.\n');
}

void main().catch((error: unknown) => {
  process.stderr.write(`${error instanceof Error ? error.stack : String(error)}\n`);
  process.exitCode = 1;
});
