/**
 * Reading the phone's own screen, on demand.
 *
 * Android will not let an app look at another app's pixels without the
 * MediaProjection grant. The flow is the honest one: ask once, start a short
 * native capture, and tell the reader to switch to the listing while a
 * foreground service takes frames. No photo library, no manual screenshot.
 *
 * The frames live in the app's own external Pictures directory; the frame
 * closest to the moment the reader was told to switch is the one kept, and the
 * rest are deleted.
 */

import * as FileSystem from 'expo-file-system/legacy';
import { Platform } from 'react-native';
import {
  addListener,
  CaptureEventType,
  PermissionStatus,
  requestPermission,
  startCapture,
  stopCapture,
  type CaptureErrorEvent,
  type FrameCapturedEvent,
} from 'react-native-frame-capture';

export interface CapturedImage {
  uri: string;
  base64: string;
  mime: string;
}

/** How long the reader has to switch apps before the frame is taken. */
export const READ_SECONDS = 4;
/** How long the native service keeps capturing. */
const CAPTURE_MS = 7_000;

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const onAbort = () => {
      clearTimeout(timer);
      reject(new Error('Screen reading stopped.'));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    signal?.addEventListener('abort', onAbort, { once: true });
    if (signal?.aborted) onAbort();
  });
}

type Frame = { uri: string; time: number; name: string };

function frameUri(path: string): string {
  return path.startsWith('file://') ? path : `file://${path}`;
}

function throwIfAborted(signal?: AbortSignal): void {
  if (signal?.aborted) throw new Error('Screen reading stopped.');
}

async function pickFrame(startedAt: number, captured: Frame[]): Promise<Frame> {
  const target = startedAt + READ_SECONDS * 1000 + 250;
  const frames = captured.filter((frame) => frame.time >= startedAt);
  if (!frames.length) {
    throw new Error(
      'No screen frame was captured. Keep Kriko in the background until the countdown ends, then try again.',
    );
  }
  frames.sort((a, b) => Math.abs(a.time - target) - Math.abs(b.time - target));
  return frames[0];
}

/** Ask, capture, and return the frame the reader was looking at. */
export async function readPhoneScreen(onStarted?: () => void, signal?: AbortSignal): Promise<CapturedImage> {
  throwIfAborted(signal);
  if (Platform.OS !== 'android') {
    throw new Error('Reading the screen is Android-only in this build.');
  }
  const status = await requestPermission();
  throwIfAborted(signal);
  if (status !== PermissionStatus.GRANTED) {
    throw new Error('Screen access was not granted.');
  }

  const captured: Frame[] = [];
  const errors: string[] = [];
  const frameListener = addListener(CaptureEventType.FRAME_CAPTURED, (event: FrameCapturedEvent) => {
    captured.push({
      uri: frameUri(event.filePath),
      name: event.filePath.split(/[\\/]/).pop() ?? event.filePath,
      time: event.timestamp,
    });
  });
  const errorListener = addListener(CaptureEventType.CAPTURE_ERROR, (event: CaptureErrorEvent) => {
    errors.push(event.message);
  });
  const startedAt = Date.now();
  let destination = '';
  let returnedImage = false;
  try {
    try {
      await startCapture({
        capture: { interval: 350, autoStopTimeout: CAPTURE_MS },
        // Fine text and small model numbers benefit from higher JPEG quality.
        image: { quality: 88, format: 'jpeg' },
        storage: { saveFrames: true, location: 'private' },
      });
      onStarted?.();

      // Native capture and auto-stop continue if Android suspends JS.
      await sleep(CAPTURE_MS + 500, signal);
      throwIfAborted(signal);
    } finally {
      await stopCapture().catch(() => {});
      frameListener.remove();
      errorListener.remove();
    }

    throwIfAborted(signal);
    if (!captured.length && errors.length) {
      throw new Error(`Screen capture failed: ${errors[0]}`);
    }
    const frame = await pickFrame(startedAt, captured);
    destination = `${FileSystem.cacheDirectory ?? ''}screen-${Date.now()}.jpg`;
    await FileSystem.copyAsync({ from: frame.uri, to: destination });
    throwIfAborted(signal);
    const info = await FileSystem.getInfoAsync(destination);
    if (!info.exists || (info.size ?? 0) < 8_000) {
      await FileSystem.deleteAsync(destination, { idempotent: true }).catch(() => {});
      throw new Error('The captured screen image is incomplete. Try again with the listing fully loaded.');
    }
    const base64 = await FileSystem.readAsStringAsync(destination, { encoding: 'base64' });
    throwIfAborted(signal);
    if (base64.length < 10_000) {
      await FileSystem.deleteAsync(destination, { idempotent: true }).catch(() => {});
      throw new Error('The captured screen image could not be read. Try again.');
    }
    returnedImage = true;
    return { uri: destination, base64, mime: 'image/jpeg' };
  } finally {
    await Promise.all([
      ...captured.map((item) => FileSystem.deleteAsync(item.uri, { idempotent: true }).catch(() => {})),
      ...(!returnedImage && destination
        ? [FileSystem.deleteAsync(destination, { idempotent: true }).catch(() => {})]
        : []),
    ]);
  }
}
