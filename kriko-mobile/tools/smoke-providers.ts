/**
 * Development smoke test: vision and search against the real providers, with
 * the keys opened from the baked trial. Prints no keys.
 *
 *   npx tsx tools/smoke-providers.ts
 */

import { readFileSync } from 'node:fs';

import { readListing, searchWeb } from '../src/engine/providers';
import { openTrial } from '../src/engine/sharekeys';

async function main() {
  const trial = openTrial();
  if (!trial) throw new Error('the baked trial did not open');

  const image = readFileSync(
    new URL('../src/assets/sample-listing.png', import.meta.url),
  ).toString('base64');

  const started = Date.now();
  const reading = await readListing(image, 'image/png', trial.keys.deepseek);
  console.log('vision:', Math.round((Date.now() - started) / 100) / 10, 's');
  console.log(reading);

  const search = await searchWeb(
    'Samsung Galaxy Buds2 Pro battery drain known issues forum',
    3,
    trial.keys.deepseek,
  );
  console.log(
    'search:',
    search.error || `${search.hits.length} hits`,
    search.hits.map((hit) => `${new URL(hit.url).hostname} (${hit.pageText.length} chars)`),
  );
}

void main();
