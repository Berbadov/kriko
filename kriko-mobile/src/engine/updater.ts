/**
 * The phone's own update, wired to its real parts: GitHub's list of releases,
 * the app's storage, and the native downloader and installer (`overlay.ts`).
 * What it decides lives in `updatecore.ts`, which tests exercise without a phone.
 *
 * Two build-time switches exist for testing an update against a local server;
 * neither is set in a release build:
 *   EXPO_PUBLIC_KRIKO_UPDATE_FEED    where the list of releases comes from
 *   EXPO_PUBLIC_KRIKO_UPDATE_ASSETS  the address every file must start with
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import { useEffect, useSyncExternalStore } from 'react';
import { AppState, Platform } from 'react-native';

import { DEFAULT_ASSET_PREFIX, DEFAULT_RELEASES_URL } from './appupdate';
import {
  canInstallApps,
  cancelUpdateDownload,
  downloadUpdateFile,
  installedVersion,
  installUpdateFile,
  openInstallAppsSettings,
  overlayAvailable,
  subscribeUpdateInstall,
  subscribeUpdateProgress,
} from './overlay';
import { createUpdater, UpdateError, type UpdateDeps, type UpdateMemory } from './updatecore';

const MEMORY_KEY = 'kriko.update.v1';
const FEED = process.env.EXPO_PUBLIC_KRIKO_UPDATE_FEED || DEFAULT_RELEASES_URL;
const ASSETS = process.env.EXPO_PUBLIC_KRIKO_UPDATE_ASSETS || DEFAULT_ASSET_PREFIX;

async function getText(url: string, accept: string): Promise<string> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15_000);
  try {
    const response = await fetch(url, { headers: { Accept: accept }, signal: controller.signal });
    // GitHub answers a visitor it is rationing with 403 or 429.
    if (response.status === 403 || response.status === 429) throw new UpdateError('rate');
    if (!response.ok) throw new UpdateError('server');
    return await response.text();
  } catch (error) {
    throw error instanceof UpdateError ? error : new UpdateError('offline');
  } finally {
    clearTimeout(timer);
  }
}

const deps: UpdateDeps = {
  releases: async () => {
    const text = await getText(FEED, 'application/vnd.github+json');
    try { return JSON.parse(text) as unknown; } catch { throw new UpdateError('server'); }
  },
  text: (url) => getText(url, 'text/plain'),
  installed: async () => (await installedVersion())?.versionName || null,
  canInstall: canInstallApps,
  openInstallSettings: openInstallAppsSettings,
  download: async (update, sha256) => { await downloadUpdateFile(update.version, update.apkUrl, sha256, update.bytes); },
  cancelDownload: cancelUpdateDownload,
  install: async (version) => { await installUpdateFile(version); },
  onProgress: subscribeUpdateProgress,
  onInstall: subscribeUpdateInstall,
  load: async (): Promise<UpdateMemory> => {
    try {
      const raw = JSON.parse(await AsyncStorage.getItem(MEMORY_KEY) || '{}') as Partial<UpdateMemory>;
      return {
        checkedAt: typeof raw.checkedAt === 'number' ? raw.checkedAt : 0,
        dismissed: typeof raw.dismissed === 'string' ? raw.dismissed : '',
        found: raw.found,
      };
    } catch {
      return { checkedAt: 0, dismissed: '' };
    }
  },
  save: (memory) => AsyncStorage.setItem(MEMORY_KEY, JSON.stringify(memory)),
  now: () => Date.now(),
  assetPrefix: ASSETS,
};

export const updater = createUpdater(deps);

/** Whether this build can fetch and install its own updates (an Android build with the native module). */
export const updatesSupported = (): boolean => Platform.OS === 'android' && overlayAvailable();

export function useAppUpdate() {
  return useSyncExternalStore(updater.subscribe, updater.getSnapshot, updater.getSnapshot);
}

/**
 * Mounted once at the app's root: a look at GitHub a few seconds after the app
 * opens (only when one is due), and a step on when the reader returns from the
 * phone's "install apps" page.
 */
export function useUpdateLifecycle(): void {
  useEffect(() => {
    if (!updatesSupported()) return undefined;
    const timer = setTimeout(() => { void updater.autoCheck(); }, 4000);
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active') void updater.resume();
    });
    return () => { clearTimeout(timer); subscription.remove(); };
  }, []);
}
