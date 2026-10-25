/**
 * Live vision smoke: open the baked trial, read the four trial photos, and
 * print timing plus the fields that came back. Never prints a key.
 *
 *   npx tsx tools/smoke-vision.ts
 */

import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';

import { readingTitle } from '../src/engine/prompt';
import { readListing, VISION_MODEL } from '../src/engine/providers';
import { openTrial } from '../src/engine/sharekeys';

const IMAGE_DIR = process.env.KRIKO_VISION_DIR ?? join(process.cwd(), '..', '.tmp-vision');
const FILES = ['metabo', 'panasonic', 'drill', 'unbranded'] as const;

function seconds(since: number): string {
  return `${((Date.now() - since) / 1000).toFixed(1)}s`;
}

function line(label: string, value: string): string {
  return `  ${label.padEnd(17)}${value}`;
}

async function main(): Promise<void> {
  const trial = openTrial();
  if (!trial) {
    process.stderr.write('The baked trial did not open in this build; nothing was called.\n');
    process.exitCode = 1;
    return;
  }

  process.stdout.write(`Vision smoke: ${VISION_MODEL}, trial access, images in ${IMAGE_DIR}\n`);
  let failed = 0;
  for (const name of FILES) {
    const path = join(IMAGE_DIR, `${name}.jpg`);
    if (!existsSync(path)) {
      process.stdout.write(`\n### ${name}.jpg MISSING at ${path}\n`);
      failed += 1;
      continue;
    }
    const base64 = readFileSync(path).toString('base64');
    const started = Date.now();
    try {
      const reading = await readListing(base64, 'image/jpeg', trial.keys.deepseek);
      const took = seconds(started);
      const candidates = reading.visualCandidates?.length
        ? reading.visualCandidates
            .map((candidate) => `${candidate.confidence}: ${candidate.name} (${candidate.reason})`)
            .join('\n                      ')
        : 'none';
      process.stdout.write([
        '',
        `### ${name}.jpg ${took}`,
        line('title', readingTitle(reading, true) || '(empty)'),
        line('brand', reading.brand || '(empty)'),
        line('product', reading.product || '(empty)'),
        line('model', reading.model || '(empty)'),
        line('price', reading.price || '(empty)'),
        line('condition', reading.condition || '(empty)'),
        line('identityBasis', reading.identityBasis ?? '(empty)'),
        line('candidates', candidates),
        line('note', reading.note || '(empty)'),
        line('detail', reading.detail ? reading.detail.slice(0, 240) : '(empty)'),
        line('visual', reading.visualDescription ? reading.visualDescription.slice(0, 240) : '(empty)'),
      ].join('\n') + '\n');
    } catch (error) {
      failed += 1;
      const message = error instanceof Error ? error.message : String(error);
      process.stdout.write(`\n### ${name}.jpg FAILED after ${seconds(started)}: ${message}\n`);
    }
  }
  process.stdout.write(`\n${FILES.length - failed}/${FILES.length} images read.\n`);
  if (failed) process.exitCode = 1;
}

void main().catch((error: unknown) => {
  process.stderr.write(`${error instanceof Error ? error.stack : String(error)}\n`);
  process.exitCode = 1;
});
