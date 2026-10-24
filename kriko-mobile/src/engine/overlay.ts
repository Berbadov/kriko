import { AppRegistry, NativeEventEmitter, NativeModules, Platform } from "react-native";

export type OverlayJob = {
  id: string;
  title: string;
  status: string;
  text?: string;
  error?: string;
  sources?: { n: number; url: string; title?: string }[];
  steps?: { kind: string; text: string }[];
};

export type OverlayScan = {
  base64: string;
  mime: string;
  uri: string;
  mode?: "research" | "site_reviews";
  reviewSite?: string;
};
export type OverlaySession = { active: boolean };
export type OverlayAction = { action: "select" | "cancel"; id: string };

type KrikoOverlayNative = {
  startSession(): Promise<void>;
  stopSession(): Promise<void>;
  isActive(): Promise<boolean>;
  ensureHeadlessSession(): void;
  updateJobs(json: string): void;
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

if (!sessionRuntime.registered) {
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

export function updateOverlayJobs(jobs: OverlayJob[]): void {
  if (overlayAvailable()) native!.updateJobs(JSON.stringify(jobs));
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
