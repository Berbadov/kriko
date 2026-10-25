/**
 * Pictures that stay in a chat.
 *
 * A scan arrives as a full phone frame and is read once. What the conversation
 * keeps is a small copy of it, in the app's own storage, so the picture is
 * still there next week and the folder never grows past what chats refer to.
 * The full frame is only a cache file for the reader's second, tighter look.
 *
 * Nothing here may fail a scan: every function resolves, and a picture that
 * could not be kept is simply a chat without one.
 */

import * as FileSystem from 'expo-file-system/legacy';
import { ImageManipulator, SaveFormat } from 'expo-image-manipulator';

import { orphanedThumbnails } from './thumbrules';

const FOLDER = 'scans/';
/** Wide enough for the card and the enlarged view, small enough to keep many. */
const THUMB_WIDTH = 640;
/** A picture younger than this is never pruned, whatever refers to it. */
const RECENT_MS = 10 * 60 * 1000;

function root(): string {
  return `${FileSystem.documentDirectory ?? ''}${FOLDER}`;
}

function stamp(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

/** Write a captured frame to the cache so the reader and the thumbnail can open it. */
export async function writeFrame(base64: string): Promise<string> {
  const base = FileSystem.cacheDirectory;
  if (!base || !base64) return '';
  const target = `${base}frame-${stamp()}.jpg`;
  try {
    await FileSystem.writeAsStringAsync(target, base64, { encoding: 'base64' });
    return target;
  } catch {
    return '';
  }
}

/** Remove a cache file this module wrote. */
export async function discardFrame(uri: string): Promise<void> {
  if (!uri) return;
  await FileSystem.deleteAsync(uri, { idempotent: true }).catch(() => {});
}

/**
 * A small, durable copy of a picture for the chat. Resolves to the kept file's
 * address, or undefined when the picture could not be copied.
 */
export async function keepThumbnail(uri: string): Promise<string | undefined> {
  const folder = root();
  if (!uri || !folder) return undefined;
  try {
    await FileSystem.makeDirectoryAsync(folder, { intermediates: true }).catch(() => {});
    const loaded = await ImageManipulator.manipulate(uri, { maxWidth: THUMB_WIDTH }).renderAsync();
    const saved = await loaded.saveAsync({ format: SaveFormat.JPEG, compress: 0.82 });
    const target = `${folder}${stamp()}.jpg`;
    await FileSystem.copyAsync({ from: saved.uri, to: target });
    await FileSystem.deleteAsync(saved.uri, { idempotent: true }).catch(() => {});
    return target;
  } catch {
    return undefined;
  }
}

/**
 * Delete stored pictures that no chat or scan refers to. Run once per launch,
 * when nothing is in flight, so a picture being attached is never in the way.
 */
export async function pruneThumbnails(referenced: Iterable<string | undefined>): Promise<void> {
  const folder = root();
  if (!folder) return;
  try {
    const names = await FileSystem.readDirectoryAsync(folder);
    const gone = orphanedThumbnails(names, referenced, folder);
    const now = Date.now();
    await Promise.all(gone.map(async (name) => {
      const uri = `${folder}${name}`;
      // A picture written in the last few minutes may belong to a scan that has
      // not reached a chat yet (an assistant scan arriving as the app starts).
      const info = await FileSystem.getInfoAsync(uri).catch(() => null);
      const written = info && info.exists && typeof info.modificationTime === 'number'
        ? info.modificationTime * 1000
        : 0;
      if (now - written < RECENT_MS) return;
      await FileSystem.deleteAsync(uri, { idempotent: true }).catch(() => {});
    }));
  } catch {
    // No folder yet, or storage is unavailable: there is nothing to prune.
  }
}
