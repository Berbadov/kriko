import assert from 'node:assert/strict';

// Exercise the real registration/bridge module with a paused sharing session.
// Power-button research must remain alive even though isActive() is false.
const Module = require('node:module');
const originalLoad = Module._load;
const listeners = new Map<string, (payload: unknown) => void>();
let taskFactory: (() => (data?: { active?: boolean }) => Promise<void>) | undefined;
Module._load = function(name: string, ...rest: unknown[]) {
  if (name === 'react-native') return {
    Platform: { OS: 'android' },
    NativeModules: { KrikoOverlay: { isActive: async () => false, ensureHeadlessSession: () => {} } },
    NativeEventEmitter: class {
      addListener(event: string, callback: (payload: unknown) => void) {
        listeners.set(event, callback);
        return { remove: () => listeners.delete(event) };
      }
    },
    AppRegistry: { registerHeadlessTask(name: string, factory: typeof taskFactory) {
      assert.equal(name, 'KrikoOverlaySession'); taskFactory = factory;
    } },
  };
  return originalLoad.call(this, name, ...rest);
};

async function main() {
  try {
    const overlay: typeof import('../src/engine/overlay') = require('../src/engine/overlay');
    assert.ok(taskFactory);
    assert.ok(listeners.has('onRuntime'), 'assistant runtime is independent of screen-sharing UI state');
    let settled = false;
    const task = taskFactory!()({ active: true }).then(() => { settled = true; });
    assert.equal(await overlay.isOverlayActive(), false, 'assistant work must not claim screen sharing is on');
    await Promise.resolve();
    assert.equal(settled, false, 'a sharing-status query cannot pause the assistant task');
    listeners.get('onRuntime')!({ active: false });
    await task;
    assert.equal(settled, true, 'native runtime completion releases the pending task');
    console.log('Assistant-only background runtime registration checks passed.');
  } finally { Module._load = originalLoad; }
}
void main();
