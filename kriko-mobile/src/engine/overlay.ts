import { AppRegistry, NativeEventEmitter, NativeModules, Platform } from "react-native";

export type OverlayJob = {
  id: string;
  title: string;
  status: string;
  text?: string;
  error?: string;
  sources?: { n: number; url: string; title?: string }[];
  steps?: { kind: string; text: string }[];
  /** A picture of the scanned page (a local file), shown beside the title. */
  image?: string;
};

export type OverlayScan = {
  base64: string;
  mime: string;
  uri: string;
  mode?: "research" | "site_reviews";
  reviewSite?: string;
};
/** `paused` means the session stands but Android ended screen capture (the phone locked). */
export type OverlaySession = { active: boolean; paused?: boolean };
export type OverlayAction = { action: "select" | "cancel"; id: string };

/** The resolved palette the native bubble and panel should draw in. */
export type OverlayTheme = "dark" | "paper" | "white";

/**
 * Every word the native bubble and panel draw, already translated.
 *
 * The native side keeps English defaults and replaces them when one of these
 * arrives, so a session that starts before the first update still reads.
 */
export type OverlayLabels = {
  scan: string;
  /** The tray's one big action, and the sheet's first button. */
  scanPage: string;
  scanAgain: string;
  results: string;
  /** The quiet disclosure that opens the review-site field. */
  siteComments: string;
  queue: string;
  stop: string;
  now: string;
  all: string;
  readSiteComments: string;
  siteUrlHint: string;
  cancel: string;
  close: string;
  queued: string;
  running: string;
  reading: string;
  done: string;
  error: string;
  cancelled: string;
  productScan: string;
  sources: string;
  queueFull: string;
  dragHint: string;
  /** The label of the drop target shown while the floating K is being dragged. */
  dropToStop: string;
  notificationTitle: string;
  notificationText: string;
  stopSharing: string;
  channelName: string;
  channelDescription: string;
  /** Native-only copy the panel and toasts would otherwise hardcode in English. */
  queueEmpty: string;
  answerEmpty: string;
  captureFailed: string;
  sourceFailed: string;
  copy: string;
  copied: string;
  scannedPage: string;
  /** The grey page: capture ended, the next Scan asks for it again. */
  paused: string;
  notificationPausedText: string;
  resumeFailed: string;
  /** The phone-assistant card: shown at once, then while the app opens. */
  openingKriko: string;
  assistScanning: string;
  assistNoShot: string;
  assistTitle: string;
  /** Toast when a phone-assistant scan is folded away while it is still being read. */
  assistKeeps: string;
};

/**
 * `puckOpacity` is a percentage, 20 to 100: how solid the floating K and the
 * glass panels around it are drawn.
 */
export type OverlayUi = { theme: OverlayTheme; labels: OverlayLabels; puckOpacity: number };

type KrikoOverlayNative = {
  startSession(): Promise<void>;
  stopSession(): Promise<void>;
  isActive(): Promise<boolean>;
  ensureHeadlessSession(): void;
  moveToBack(): Promise<boolean>;
  setAppForeground(foreground: boolean): void;
  setUiReady(ready: boolean): void;
  isDefaultAssistant(): Promise<boolean>;
  openAssistantSettings(): Promise<boolean>;
  canDrawOverlays(): Promise<boolean>;
  openOverlaySettings(): Promise<boolean>;
  updateJobs(json: string): void;
  updateUi(json: string): void;
  appVersion(): Promise<{ versionName: string; versionCode: number }>;
  canInstallPackages(): Promise<boolean>;
  openInstallSettings(): Promise<boolean>;
  downloadUpdate(version: string, url: string, sha256: string, bytes: number): Promise<{ sha256: string; bytes: number }>;
  cancelUpdate(): void;
  installUpdate(version: string): Promise<boolean>;
  addListener(eventName: string): void;
  removeListeners(count: number): void;
};

type OverlaySessionRuntime = {
  active: boolean;
  registered: boolean;
  resolveTask?: () => void;
  listener?: { remove(): void };
};

const globalRuntime = globalThis as typeof globalThis & {
  __krikoOverlaySessionRuntime?: OverlaySessionRuntime;
};
const sessionRuntime = globalRuntime.__krikoOverlaySessionRuntime
  || (globalRuntime.__krikoOverlaySessionRuntime = { active: false, registered: false });

const native = NativeModules.KrikoOverlay as KrikoOverlayNative | undefined;
const events = native ? new NativeEventEmitter(native as never) : null;

if (events && !sessionRuntime.listener) {
  sessionRuntime.listener = events.addListener("onSession", (payload) => {
    sessionRuntime.active = Boolean((payload as OverlaySession)?.active);
    if (!sessionRuntime.active) {
      const resolve = sessionRuntime.resolveTask;
      sessionRuntime.resolveTask = undefined;
      resolve?.();
    }
  });
}

if (Platform.OS === 'android' && !sessionRuntime.registered) {
  AppRegistry.registerHeadlessTask("KrikoOverlaySession", () => async () => {
    if (!sessionRuntime.active) return;
    await new Promise<void>((resolve) => {
      sessionRuntime.resolveTask = resolve;
      if (!sessionRuntime.active) {
        sessionRuntime.resolveTask = undefined;
        resolve();
      }
    });
  });
  sessionRuntime.registered = true;
}

/** Whether this build contains the Android overlay module (false in Expo Go). */
export function overlayAvailable(): boolean {
  return Platform.OS === "android" && Boolean(native && events);
}

export function isOverlayActive(): Promise<boolean> {
  if (!overlayAvailable()) return Promise.resolve(false);
  return native!.isActive().then((active) => {
    sessionRuntime.active = active;
    if (active) native!.ensureHeadlessSession();
    return active;
  });
}

export function startOverlaySession(): Promise<void> {
  if (!overlayAvailable()) {
    return Promise.reject(new Error("The Android floating scan bubble is unavailable in this build."));
  }
  return native!.startSession().then(() => {
    sessionRuntime.active = true;
    native!.ensureHeadlessSession();
  });
}

export function stopOverlaySession(): Promise<void> {
  return overlayAvailable() ? native!.stopSession() : Promise.resolve();
}

/**
 * Tell the scanner whether Kriko's own screen is in front. It floats over the
 * reader's page, so it stands down while the app is showing and returns the
 * moment the reader moves on.
 */
export function setOverlayAppForeground(foreground: boolean): void {
  if (overlayAvailable()) native!.setAppForeground(foreground);
}

/**
 * Send Kriko's own window behind whatever the reader was looking at, so the
 * scanner floats over their page and not over Kriko. Resolves false when there
 * is nothing to step aside for (no native module, or no activity).
 */
export function moveAppToBack(): Promise<boolean> {
  if (!overlayAvailable()) return Promise.resolve(false);
  return native!.moveToBack().catch(() => false);
}

/**
 * Tell the scanner whether Kriko's screen is mounted and listening. The scanner
 * outlives the screen; while nobody listens it opens the app with the picture.
 */
export function setOverlayUiReady(ready: boolean): void {
  if (overlayAvailable()) native!.setUiReady(ready);
}

/** Whether Kriko is the phone's chosen digital assistant (power or home long-press). */
export function isDefaultAssistant(): Promise<boolean> {
  if (!overlayAvailable()) return Promise.resolve(false);
  return native!.isDefaultAssistant().catch(() => false);
}

/** Open the phone's own page for choosing the digital assistant. */
export function openAssistantSettings(): Promise<boolean> {
  if (!overlayAvailable()) return Promise.resolve(false);
  return native!.openAssistantSettings().catch(() => false);
}

/**
 * Whether Kriko may draw over other apps. The phone assistant needs it to show
 * its answer over the reader's own page; without it the answer opens in the app.
 */
export function canDrawOverApps(): Promise<boolean> {
  if (!overlayAvailable()) return Promise.resolve(false);
  return native!.canDrawOverlays().catch(() => false);
}

/** Open the phone's own page for allowing Kriko to draw over other apps. */
export function openDrawOverAppsSettings(): Promise<boolean> {
  if (!overlayAvailable()) return Promise.resolve(false);
  return native!.openOverlaySettings().catch(() => false);
}

export function updateOverlayJobs(jobs: OverlayJob[]): void {
  if (overlayAvailable()) native!.updateJobs(JSON.stringify(jobs));
}

/**
 * Hand the native bubble and panel their palette and words.
 *
 * Sent even while no session runs: the module keeps the last payload and
 * starts the bubble already in the reader's theme and language instead of
 * flashing English and dark first. `updateJobs` is untouched.
 */
export function updateOverlayUi(ui: OverlayUi): void {
  if (overlayAvailable()) native!.updateUi(JSON.stringify(ui));
}

export function subscribeOverlayScan(callback: (scan: OverlayScan) => void): () => void {
  if (!events) return () => undefined;
  const subscription = events.addListener("onScan", (payload) => callback(payload as OverlayScan));
  return () => subscription.remove();
}

export function subscribeOverlaySession(callback: (session: OverlaySession) => void): () => void {
  if (!events) return () => undefined;
  const subscription = events.addListener("onSession", (payload) => callback(payload as OverlaySession));
  return () => subscription.remove();
}

export function subscribeOverlayAction(callback: (action: OverlayAction) => void): () => void {
  if (!events) return () => undefined;
  const subscription = events.addListener("onAction", (payload) => callback(payload as OverlayAction));
  return () => subscription.remove();
}

/** What the phone itself says is installed: `versionName` as shown, `versionCode` as Android orders builds. */
export function installedVersion(): Promise<{ versionName: string; versionCode: number } | null> {
  if (!overlayAvailable()) return Promise.resolve(null);
  return native!.appVersion().catch(() => null);
}

/** Whether the phone lets Kriko install an app. Off until the reader allows it once. */
export function canInstallApps(): Promise<boolean> {
  if (!overlayAvailable()) return Promise.resolve(false);
  return native!.canInstallPackages().catch(() => false);
}

/** Open the phone's own page for allowing Kriko to install apps. */
export function openInstallAppsSettings(): Promise<boolean> {
  if (!overlayAvailable()) return Promise.resolve(false);
  return native!.openInstallSettings().catch(() => false);
}

const noInstaller = () => Object.assign(new Error(), { code: 'unavailable' });

/**
 * Download one version into the app's own cache and verify it. Rejects with the
 * native failure kind as `code`: network, checksum, size, storage, cancelled, busy.
 */
export function downloadUpdateFile(version: string, url: string, sha256: string, bytes: number): Promise<{ sha256: string; bytes: number }> {
  if (!overlayAvailable()) return Promise.reject(noInstaller());
  return native!.downloadUpdate(version, url, sha256, bytes);
}

export function cancelUpdateDownload(): void {
  if (overlayAvailable()) native!.cancelUpdate();
}

/**
 * Hand the downloaded version to Android's installer. Rejects with `permission`
 * (not yet allowed), `signature` (another key), `older`, `invalid`, `missing`, `storage`.
 */
export function installUpdateFile(version: string): Promise<boolean> {
  if (!overlayAvailable()) return Promise.reject(noInstaller());
  return native!.installUpdate(version);
}

export type UpdateProgress = { received: number; total: number };
export type UpdateInstall = {
  state: 'confirm' | 'installed' | 'cancelled' | 'blocked' | 'signature' | 'storage' | 'failed';
  message: string;
};

export function subscribeUpdateProgress(callback: (progress: UpdateProgress) => void): () => void {
  if (!events) return () => undefined;
  const subscription = events.addListener("onUpdateProgress", (payload) => callback(payload as UpdateProgress));
  return () => subscription.remove();
}

export function subscribeUpdateInstall(callback: (install: UpdateInstall) => void): () => void {
  if (!events) return () => undefined;
  const subscription = events.addListener("onUpdateInstall", (payload) => callback(payload as UpdateInstall));
  return () => subscription.remove();
}
