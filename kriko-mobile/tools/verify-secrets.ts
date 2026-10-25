/**
 * Cross-check the phone's shared-access crypto against the desktop tool that
 * made the bundle. Prints only hashes: the keys never leave the process.
 *
 *   npx tsx tools/verify-secrets.ts
 *
 * It is a development check, not part of the app.
 */

import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';

import { openAccess, openTrial } from '../src/engine/sharekeys';

function digest(value: string): string {
  return createHash('sha256').update(value).digest('hex');
}

const text = readFileSync(new URL('../.friend-access.txt', import.meta.url), 'utf8');
const password = text.match(/^password: (.*)$/m)?.[1]?.trim() ?? '';
const code = text.match(/^code: (.*)$/m)?.[1]?.trim() ?? '';

const trial = openTrial();
if (!trial) {
  console.error('FAIL: the baked trial does not open');
  process.exit(1);
}
console.log('trial opens: yes');
console.log('trial limit:', trial.limit);
console.log('trial key digest:', digest(`${trial.keys.mercury}\n${trial.keys.deepseek}`).slice(0, 16));

try {
  const keys = openAccess(code, password);
  console.log('access opens: yes');
  console.log('access key digest:', digest(`${keys.mercury}\n${keys.deepseek}`).slice(0, 16));
} catch (error) {
  console.error('FAIL: the access code did not open:', error instanceof Error ? error.message : error);
  process.exit(1);
}

try {
  openAccess(code, 'definitely-not-the-password');
  console.error('FAIL: the wrong password opened the code');
  process.exit(1);
} catch {
  console.log('wrong password refused: yes');
}
