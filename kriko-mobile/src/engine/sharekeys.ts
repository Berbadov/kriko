/**
 * Shared access, on the phone: the owner's keys behind a password.
 *
 * The wire format is `src/app/sharekeys.py` on the desktop, byte for byte. A
 * friend pastes the code and the password; the code carries the owner's Mercury
 * and DeepSeek keys, sealed with AES-256-GCM under a key derived with scrypt
 * from the password, the build pepper, and a per-code salt. Without the pepper
 * — which is baked into the APK and is not in this repository — the code and
 * password open nothing, which is the promise the password makes.
 *
 * The trial bundle is the same seal with no password, keyed from the pepper
 * alone. It is a courtesy, not a wall: the count lives on the phone and the
 * owner's real protection is the spend limit on the key it carries.
 *
 * Nothing is written here in the clear; the caller keeps the opened keys in
 * SecureStore.
 */

import { gcm } from '@noble/ciphers/aes.js';
import { scrypt } from '@noble/hashes/scrypt.js';
import { utf8ToBytes } from '@noble/hashes/utils.js';

import { PEPPER, TRIAL_BUNDLE, TRIAL_QUESTIONS } from './secrets';
import type { ProviderKeys } from './types';

const PREFIX = new Uint8Array([0x4b, 0x53, 0x41, 0x31]); // "KSA1"
const GRANT_AAD = utf8ToBytes('kriko/shared-access/grant/v1');
const TRIAL_AAD = utf8ToBytes('kriko/shared-access/trial/v1');

const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_';

function b64urlToBytes(text: string): Uint8Array {
  const clean = text.replace(/=+$/, '');
  const out = new Uint8Array(Math.floor((clean.length * 3) / 4));
  let value = 0;
  let bits = 0;
  let index = 0;
  for (const character of clean) {
    const digit = B64.indexOf(character);
    if (digit < 0) throw new Error('not base64url');
    value = ((value << 6) | digit) & 0xffffff;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      out[index] = (value >> bits) & 0xff;
      index += 1;
    }
  }
  return out.subarray(0, index);
}

function hexOf(bytes: Uint8Array): string {
  let out = '';
  for (const byte of bytes) out += byte.toString(16).padStart(2, '0');
  return out;
}

/** UTF-8 decode without assuming `TextDecoder` exists in Hermes. */
function utf8Decode(bytes: Uint8Array): string {
  let out = '';
  let index = 0;
  while (index < bytes.length) {
    const first = bytes[index];
    index += 1;
    if (first < 0x80) {
      out += String.fromCharCode(first);
    } else if (first < 0xe0) {
      out += String.fromCharCode(((first & 0x1f) << 6) | (bytes[index] & 0x3f));
      index += 1;
    } else if (first < 0xf0) {
      out += String.fromCharCode(
        ((first & 0x0f) << 12) | ((bytes[index] & 0x3f) << 6) | (bytes[index + 1] & 0x3f),
      );
      index += 2;
    } else {
      const point =
        ((first & 0x07) << 18) |
        ((bytes[index] & 0x3f) << 12) |
        ((bytes[index + 1] & 0x3f) << 6) |
        (bytes[index + 2] & 0x3f);
      out += String.fromCodePoint(point);
      index += 3;
    }
  }
  return out;
}

function hasPrefix(blob: Uint8Array): boolean {
  if (blob.length < PREFIX.length) return false;
  return PREFIX.every((byte, index) => blob[index] === byte);
}

/** The desktop's `_scrypt_key`: password, a NUL, then the pepper encoded as hex. */
function passwordKey(password: string, salt: Uint8Array): Uint8Array {
  const material = utf8ToBytes(`${password}\0${hexOf(utf8ToBytes(PEPPER))}`);
  return scrypt(material, salt, {
    N: 2 ** 15,
    r: 8,
    p: 1,
    dkLen: 32,
    maxmem: 96 * 1024 * 1024,
  });
}

/** The desktop's `_pepper_key`: the pepper's own bytes as the passphrase. */
function pepperKey(purpose: Uint8Array): Uint8Array {
  const material = PEPPER ? utf8ToBytes(PEPPER) : utf8ToBytes('kriko-without-a-pepper');
  return scrypt(material, purpose, {
    N: 2 ** 14,
    r: 8,
    p: 1,
    dkLen: 32,
    maxmem: 96 * 1024 * 1024,
  });
}

function openSealed(code: string, key: Uint8Array, aad: Uint8Array): Record<string, unknown> {
  const text = String(code || '')
    .replace(/[\s]+/g, '');
  let blob: Uint8Array;
  try {
    blob = b64urlToBytes(text);
  } catch {
    throw new Error('That does not look like an access code. Copy the whole line.');
  }
  if (!hasPrefix(blob) || blob.length < PREFIX.length + 12 + 16) {
    throw new Error('That does not look like an access code. Copy the whole line.');
  }
  const nonce = blob.slice(PREFIX.length, PREFIX.length + 12);
  const ciphertext = blob.slice(PREFIX.length + 12);
  let opened: Uint8Array;
  try {
    opened = gcm(key, nonce, aad).decrypt(ciphertext);
  } catch {
    throw new Error(
      'Could not open it: the password is not the one this code was made with, or the code was changed on the way.',
    );
  }
  let payload: unknown;
  try {
    payload = JSON.parse(utf8Decode(opened));
  } catch {
    throw new Error('The code opened, but carried nothing readable.');
  }
  if (!payload || typeof payload !== 'object') {
    throw new Error('The code opened, but carried nothing readable.');
  }
  return payload as Record<string, unknown>;
}

function keysOf(payload: Record<string, unknown>): ProviderKeys | null {
  const mercury = typeof payload.mercury === 'string' ? payload.mercury.trim() : '';
  const deepseek = typeof payload.deepseek === 'string' ? payload.deepseek.trim() : '';
  if (!mercury || !deepseek) return null;
  return { mercury, deepseek };
}

/** True when this build carries the pepper the owner's codes are sealed with. */
export function canOpenCodes(): boolean {
  return Boolean(PEPPER);
}

/** True when this build carries a trial bundle a stranger can open. */
export function hasTrialBundle(): boolean {
  return Boolean(TRIAL_BUNDLE);
}

export interface TrialAccess {
  keys: ProviderKeys;
  limit: number;
}

/**
 * The friend's side of an access code. Throws a sentence the reader can act on;
 * the caller shows it as the field's error and keeps nothing.
 */
export function openAccess(code: string, password: string): ProviderKeys {
  const text = String(code || '')
    .replace(/\s+/g, '')
    .replace(/^code:/i, '');
  const pass = String(password || '')
    .trim()
    .replace(/^password\s*:\s*/i, '');
  const dot = text.indexOf('.');
  if (dot < 0) {
    throw new Error('That does not look like an access code. Copy the whole line.');
  }
  if (!canOpenCodes()) {
    throw new Error('This build cannot open access codes: it was made without its share pepper.');
  }
  if (!pass) {
    throw new Error('Paste the password that came with the code as well.');
  }
  let salt: Uint8Array;
  try {
    salt = b64urlToBytes(text.slice(0, dot));
  } catch {
    throw new Error('That does not look like an access code. Copy the whole line.');
  }
  if (!hasPrefix(salt) || salt.length !== PREFIX.length + 16) {
    throw new Error('That does not look like an access code. Copy the whole line.');
  }
  const payload = openSealed(
    text.slice(dot + 1),
    passwordKey(pass, salt.slice(PREFIX.length)),
    GRANT_AAD,
  );
  const keys = keysOf(payload);
  if (!keys) throw new Error('That code carries no keys.');
  return keys;
}

/** The baked trial, or null when this build has none or cannot open it. */
export function openTrial(): TrialAccess | null {
  if (!TRIAL_BUNDLE) return null;
  try {
    const payload = openSealed(TRIAL_BUNDLE, pepperKey(TRIAL_AAD), TRIAL_AAD);
    const keys = keysOf(payload);
    if (!keys) return null;
    const asked = Number(payload.questions);
    return { keys, limit: Number.isFinite(asked) ? Math.max(1, Math.min(999, Math.floor(asked))) : TRIAL_QUESTIONS };
  } catch {
    return null;
  }
}
