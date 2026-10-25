/**
 * Development smoke test: one full Kriko Agent turn through the phone's engine.
 * xhr2 stands in for React Native's XMLHttpRequest; in the app the platform
 * implementation streams the same SSE frames.
 *
 *   npx tsx tools/smoke-turn.ts
 */

import XHR from 'xhr2';

import { runTurn } from '../src/engine/providers';
import { openTrial } from '../src/engine/sharekeys';

(globalThis as { XMLHttpRequest?: unknown }).XMLHttpRequest = XHR;

async function main() {
  const trial = openTrial();
  if (!trial) throw new Error('the baked trial did not open');

  let streamed = '';
  const started = Date.now();
  const result = await runTurn({
    keys: trial.keys,
    history: [],
    question:
      'What is known to go wrong with the Samsung Galaxy Buds2 Pro, and what should I check before buying a used pair for $90?',
    onText: (delta) => {
      streamed += delta;
    },
    onStep: (kind, text) => console.log(`step[${kind}]`, text),
  });

  console.log('seconds:', Math.round((Date.now() - started) / 100) / 10);
  console.log('searches:', result.searches, 'reads:', result.reads, 'unverified:', result.unverified);
  console.log('sources:', result.sources.map((source) => `[${source.n}] ${source.host}`));
  console.log('streamed chars:', streamed.length);
  console.log('error:', result.error || '(none)');
  console.log('\n--- answer ---\n' + result.text);
}

void main();
