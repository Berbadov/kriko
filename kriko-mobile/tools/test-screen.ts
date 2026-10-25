/** Offline lifecycle checks for the Android screen capture flow. */
import assert from 'node:assert/strict';
import Module from 'node:module';

type Listener = { callback: (event: any) => void; remove: () => void };
const listeners: Listener[] = [];
const deleted: string[] = [];
let permission: Promise<string> = Promise.resolve('granted');
let permissionRequests = 0;
let starts = 0;
let stops = 0;
let startError: Error | null = null;
let frameOnStart: { filePath: string; timestamp: number } | null = null;
let afterCopy: (() => void) | null = null;

const fileSystem = {
  cacheDirectory: 'file:///cache/',
  copyAsync: async ({ from, to }: { from: string; to: string }) => {
    assert.ok(from.startsWith('file://'));
    assert.ok(to.startsWith('file:///cache/'));
    afterCopy?.();
  },
  getInfoAsync: async () => ({ exists: true, size: 12_000 }),
  readAsStringAsync: async () => 'x'.repeat(12_000),
  deleteAsync: async (uri: string) => { deleted.push(uri); },
};
const frameCapture = {
  CaptureEventType: { FRAME_CAPTURED: 'frame', CAPTURE_ERROR: 'error' },
  PermissionStatus: { GRANTED: 'granted' },
  requestPermission: async () => { permissionRequests += 1; return permission; },
  addListener: (_event: string, callback: (event: any) => void) => {
    const listener = { callback, remove: () => { listenerRemoved += 1; } };
    listeners.push(listener);
    return { remove: listener.remove };
  },
  startCapture: async () => {
    starts += 1;
    if (startError) throw startError;
    if (frameOnStart) {
      listeners.find((item) => item.callback)?.callback({ ...frameOnStart, timestamp: Date.now() });
    }
  },
  stopCapture: async () => { stops += 1; },
};
let listenerRemoved = 0;

const moduleLoader = Module as any;
const originalLoad = moduleLoader._load;
moduleLoader._load = function (request: string, parent: NodeModule | null, isMain: boolean) {
  if (request === 'expo-file-system/legacy') return fileSystem;
  if (request === 'react-native-frame-capture') return frameCapture;
  if (request === 'react-native') return { Platform: { OS: 'android' } };
  return originalLoad.call(this, request, parent, isMain);
};

const originalSetTimeout = global.setTimeout;
global.setTimeout = ((callback: (...args: any[]) => void, _delay?: number, ...args: any[]) =>
  originalSetTimeout(callback, 0, ...args)) as typeof setTimeout;

const { readPhoneScreen } = require('../src/engine/screen') as typeof import('../src/engine/screen');

function reset(): void {
  listeners.length = 0;
  deleted.length = 0;
  permission = Promise.resolve('granted');
  permissionRequests = starts = stops = listenerRemoved = 0;
  startError = null;
  frameOnStart = null;
  afterCopy = null;
}

async function permissionDenialDoesNotStartCapture(): Promise<void> {
  reset();
  permission = Promise.resolve('denied');
  await assert.rejects(readPhoneScreen(), /was not granted/);
  assert.equal(starts, 0);
  assert.equal(listeners.length, 0);
}

async function cancellationWhilePermissionDialogIsPendingDoesNotStart(): Promise<void> {
  reset();
  let resolvePermission!: (value: string) => void;
  permission = new Promise((resolve) => { resolvePermission = resolve; });
  const controller = new AbortController();
  const pending = readPhoneScreen(undefined, controller.signal);
  controller.abort();
  resolvePermission('granted');
  await assert.rejects(pending, /stopped/);
  assert.equal(starts, 0);
}

async function captureCancellationStopsAndDeletesTemporaryFrame(): Promise<void> {
  reset();
  frameOnStart = { filePath: '/private/frame-1.jpg', timestamp: Date.now() };
  const controller = new AbortController();
  await assert.rejects(
    readPhoneScreen(() => controller.abort(), controller.signal),
    /stopped/,
  );
  assert.equal(starts, 1);
  assert.equal(stops, 1);
  assert.equal(listenerRemoved, 2);
  assert.deepEqual(deleted, ['file:///private/frame-1.jpg']);
}

async function successfulCaptureReturnsCopyAndCleansFrame(): Promise<void> {
  reset();
  frameOnStart = { filePath: '/private/frame-2.jpg', timestamp: Date.now() };
  const result = await readPhoneScreen();
  assert.equal(result.mime, 'image/jpeg');
  assert.ok(result.uri.startsWith('file:///cache/screen-'));
  assert.equal(result.base64.length, 12_000);
  assert.deepEqual(deleted, ['file:///private/frame-2.jpg']);
  assert.equal(stops, 1);
  assert.equal(listenerRemoved, 2);
}

async function lateCancellationDeletesUnreturnedCopy(): Promise<void> {
  reset();
  frameOnStart = { filePath: '/private/frame-3.jpg', timestamp: Date.now() };
  const controller = new AbortController();
  afterCopy = () => controller.abort();
  await assert.rejects(readPhoneScreen(undefined, controller.signal), /stopped/);
  assert.equal(stops, 1);
  assert.ok(deleted.includes('file:///private/frame-3.jpg'));
  assert.ok(deleted.some((uri) => uri.startsWith('file:///cache/screen-')));
}

async function startFailureStillStopsAndRemovesListeners(): Promise<void> {
  reset();
  startError = new Error('native start failed');
  await assert.rejects(readPhoneScreen(), /native start failed/);
  assert.equal(stops, 1);
  assert.equal(listenerRemoved, 2);
}

async function main(): Promise<void> {
  await permissionDenialDoesNotStartCapture();
  await cancellationWhilePermissionDialogIsPendingDoesNotStart();
  await captureCancellationStopsAndDeletesTemporaryFrame();
  await successfulCaptureReturnsCopyAndCleansFrame();
  await lateCancellationDeletesUnreturnedCopy();
  await startFailureStillStopsAndRemovesListeners();
  global.setTimeout = originalSetTimeout;
  moduleLoader._load = originalLoad;
  console.log('screen lifecycle checks passed');
}

void main();
