import assert from 'node:assert/strict';
import Module from 'node:module';
import { VoiceDraftSession, voiceDraft } from '../src/engine/voicecore';

const first = new VoiceDraftSession('first', 'I need');
assert.deepEqual(first.accept({ sessionId: 'first', status: 'result', text: 'a quiet', final: false }), { text: 'I need a quiet', terminal: false });
assert.deepEqual(first.accept({ sessionId: 'first', status: 'result', text: 'a quiet laptop', final: true }), { text: 'I need a quiet laptop', terminal: true });
assert.equal(first.accept({ sessionId: 'first', status: 'result', text: 'late duplicate', final: true }), null);

const second = new VoiceDraftSession('second', 'Keep my words');
assert.equal(second.accept({ sessionId: 'first', status: 'error', code: 'no_match' }), null);
assert.equal(second.active, true, 'an older error cannot stop the current microphone');
second.cancel();
assert.equal(second.accept({ sessionId: 'second', status: 'result', text: 'late words', final: true }), null);
assert.equal(second.base, 'Keep my words', 'cancelling can restore the original draft');

const failed = new VoiceDraftSession('failed', 'Typed question');
assert.deepEqual(failed.accept({ sessionId: 'failed', status: 'error', code: 'permission' }), { terminal: true });
assert.equal(failed.base, 'Typed question');
assert.equal(voiceDraft('  ', '  sessiz bir bilgisayar  '), 'sessiz bir bilgisayar');
assert.equal(voiceDraft('Typed question', ''), 'Typed question');
assert.equal(voiceDraft('a'.repeat(1998), 'spoken words').length, 2000);
assert.equal(voiceDraft('', 'Babam için kolay bir telefon'), 'Babam için kolay bir telefon');
console.log('Voice draft and cancellation checks passed.');

async function permissionAndCancellation() {
  let available = true;
  let alreadyAllowed = false;
  let starts = 0;
  let requests = 0;
  let resolvePermission!: (value: string) => void;
  let onRequest!: () => void;
  let eventListener: (event: unknown) => void = () => {};
  let removed = false;
  let permission = new Promise<string>((resolve) => { resolvePermission = resolve; });
  const bridge = {
    voiceTypingAvailable: async () => available,
    startVoiceTyping: async (locale: string, id: string) => {
      assert.equal(locale, 'tr-TR'); assert.equal(id, 'wanted'); starts++; return true;
    },
    stopVoiceTyping: () => {}, cancelVoiceTyping: () => {},
    addListener: () => {}, removeListeners: () => {},
  };
  const mock = {
    Platform: { OS: 'android' }, NativeModules: { KrikoOverlay: bridge },
    PermissionsAndroid: {
      PERMISSIONS: { RECORD_AUDIO: 'audio' }, RESULTS: { GRANTED: 'granted' },
      check: async () => alreadyAllowed,
      request: async () => { requests++; onRequest?.(); return permission; },
    },
    NativeEventEmitter: class {
      addListener(_name: string, callback: (event: unknown) => void) {
        eventListener = callback; return { remove: () => { removed = true; } };
      }
    },
  };
  const loader = Module as unknown as { _load: (name: string, parent: unknown, main: boolean) => unknown };
  const original = loader._load;
  loader._load = function (name, parent, main) { return name === 'react-native' ? mock : original.call(this, name, parent, main); };
  let adapter: typeof import('../src/engine/voice');
  try { adapter = await import('../src/engine/voice'); } finally { loader._load = original; }
  assert.equal(starts, 0, 'mounting must never turn on the microphone');
  let wanted = true;
  const asked = new Promise<void>((resolve) => { onRequest = resolve; });
  const pending = adapter.startVoiceTyping('tr-TR', 'cancelled', () => wanted);
  await asked;
  wanted = false;
  resolvePermission('granted');
  await pending;
  assert.equal(starts, 0, 'granting permission after cancellation must not start recording');
  permission = Promise.resolve('denied');
  await assert.rejects(adapter.startVoiceTyping('tr-TR', 'denied', () => true), (error: { code: string }) => error.code === 'permission');
  assert.equal(starts, 0);
  alreadyAllowed = true;
  await adapter.startVoiceTyping('tr-TR', 'wanted', () => true);
  assert.equal(starts, 1);
  assert.equal(requests, 2, 'existing permission is reused without another prompt');
  available = false;
  await assert.rejects(adapter.startVoiceTyping('tr-TR', 'unavailable', () => true), (error: { code: string }) => error.code === 'unavailable');
  assert.equal(starts, 1);
  let events = 0;
  const off = adapter.subscribeVoiceTyping(() => { events++; });
  eventListener(null); eventListener({ status: 'result' });
  eventListener({ sessionId: 'wanted', status: 'result', text: 'hello', final: true });
  assert.equal(events, 1);
  off(); assert.equal(removed, true);
  console.log('Voice microphone permission and late-cancellation checks passed.');
}
permissionAndCancellation().catch((error) => { console.error(error); process.exitCode = 1; });
