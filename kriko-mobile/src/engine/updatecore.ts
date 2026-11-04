/**
 * The in-app update, as a small state machine with everything it touches handed
 * in: the list of releases, the file download, the phone's installer, the
 * clock and the little it remembers. Nothing here imports React Native, so the
 * whole flow (check, download, ask for permission, install, every way it can
 * fail) is exercised in tests without a phone; `updater.ts` wires the real parts.
 *
 * The reader is always the one who starts a download. A look at GitHub happens
 * by itself at most twice a day and only ever tells them an update exists.
 */

import { checkIsDue, parseChecksum, pickUpdate, restoreUpdate, type AppUpdate } from './appupdate';

/** Why a step failed, as a word the screen can put in the reader's language. */
export type UpdateFailure =
  | 'offline' | 'rate' | 'server'
  | 'checksum' | 'size' | 'storage'
  | 'signature' | 'blocked' | 'older' | 'invalid' | 'missing' | 'failed';

export type UpdateStep = 'check' | 'download' | 'install';

export type UpdateState =
  | { phase: 'idle' }
  | { phase: 'checking'; manual: boolean }
  | { phase: 'current'; checkedAt: number }
  | { phase: 'available'; update: AppUpdate }
  | { phase: 'downloading'; update: AppUpdate; received: number; total: number }
  /** Downloaded; the phone has to be told once that Kriko may install apps. */
  | { phase: 'permission'; update: AppUpdate }
  | { phase: 'installing'; update: AppUpdate; confirming: boolean }
  | { phase: 'error'; step: UpdateStep; reason: UpdateFailure; update?: AppUpdate };

export type UpdateSnapshot = {
  state: UpdateState;
  /** The version the phone reports; empty where an update cannot be installed (no installer). */
  installed: string;
  /** The version whose banner the reader sent away; empty when none. */
  dismissed: string;
};

/** Whether something in the update needs the reader: a new version, a step they must take, or a failure to retry. */
export function updateNeedsAttention(snapshot: UpdateSnapshot): boolean {
  const state = snapshot.state;
  return state.phase === 'available' || state.phase === 'downloading' || state.phase === 'permission'
    || state.phase === 'installing' || (state.phase === 'error' && state.update !== undefined);
}

/** A failure a dependency throws on purpose, with the word for it. */
export class UpdateError extends Error {
  readonly reason: UpdateFailure;
  constructor(reason: UpdateFailure, message = reason) {
    super(message);
    this.reason = reason;
  }
}

/** What the phone keeps between runs: when it last looked, what was sent away, and the update it found. */
export type UpdateMemory = { checkedAt: number; dismissed: string; found?: unknown };

export type UpdateDeps = {
  /** The parsed list of releases; throws `UpdateError` ('offline', 'rate', 'server'). */
  releases(): Promise<unknown>;
  /** The text of a small file (a checksum); throws like `releases`. */
  text(url: string): Promise<string>;
  /** `versionName` of what is installed, or null where there is no installer. */
  installed(): Promise<string | null>;
  canInstall(): Promise<boolean>;
  openInstallSettings(): Promise<boolean>;
  /** Fetch and verify the file; rejects with `{ code }` (the native failure kind). */
  download(update: AppUpdate, sha256: string): Promise<void>;
  cancelDownload(): void;
  /** Give the file to the installer; rejects with `{ code }`. */
  install(version: string): Promise<void>;
  onProgress(callback: (progress: { received: number; total: number }) => void): () => void;
  onInstall(callback: (event: { state: string; message: string }) => void): () => void;
  load(): Promise<UpdateMemory>;
  save(memory: UpdateMemory): Promise<void>;
  now(): number;
  assetPrefix?: string;
};

const KNOWN: ReadonlySet<string> = new Set([
  'checksum', 'size', 'storage', 'signature', 'blocked', 'older', 'invalid', 'missing',
]);

/** A native failure kind, or a thrown error, as one of the screen's words. */
export function failureFrom(error: unknown): UpdateFailure | 'cancelled' | 'busy' | 'permission' {
  if (error instanceof UpdateError) return error.reason;
  const code = typeof error === 'object' && error !== null ? (error as { code?: unknown }).code : undefined;
  if (typeof code !== 'string') return 'failed';
  if (code === 'cancelled' || code === 'busy' || code === 'permission') return code;
  if (code === 'network') return 'offline';
  return KNOWN.has(code) ? code as UpdateFailure : 'failed';
}

export function createUpdater(deps: UpdateDeps) {
  let snapshot: UpdateSnapshot = { state: { phase: 'idle' }, installed: '', dismissed: '' };
  let memory: UpdateMemory = { checkedAt: 0, dismissed: '' };
  let loaded: Promise<void> | null = null;
  const listeners = new Set<() => void>();

  const publish = (patch: Partial<UpdateSnapshot>) => {
    snapshot = { ...snapshot, ...patch };
    listeners.forEach((listener) => listener());
  };
  const set = (state: UpdateState) => publish({ state });
  const busy = () => {
    const phase = snapshot.state.phase;
    return phase === 'checking' || phase === 'downloading' || phase === 'installing';
  };
  const remember = async (patch: Partial<UpdateMemory>) => {
    memory = { ...memory, ...patch };
    try { await deps.save(memory); } catch { /* the reader loses a note, not an update */ }
  };
  const load = () => {
    loaded ??= (async () => {
      try { memory = await deps.load(); } catch { /* start with nothing remembered */ }
      publish({ dismissed: memory.dismissed });
    })();
    return loaded;
  };

  const unsubscribers = [
    deps.onProgress((progress) => {
      const state = snapshot.state;
      if (state.phase === 'downloading') set({ ...state, received: progress.received, total: progress.total });
    }),
    deps.onInstall((event) => {
      const state = snapshot.state;
      const update = 'update' in state ? state.update : undefined;
      if (state.phase !== 'installing' || !update) return;
      if (event.state === 'confirm') set({ ...state, confirming: true });
      else if (event.state === 'installed') set({ phase: 'current', checkedAt: deps.now() });
      else if (event.state === 'cancelled') set({ phase: 'available', update });
      else {
        const reason = failureFrom({ code: event.state });
        set({ phase: 'error', step: 'install', reason: reason === 'cancelled' || reason === 'busy' || reason === 'permission' ? 'failed' : reason, update });
      }
    }),
  ];

  async function check(manual: boolean): Promise<void> {
    if (busy()) return;
    // Claimed before the first await, so a second look started meanwhile sees it.
    const before = snapshot.state;
    set({ phase: 'checking', manual });
    try {
      await load();
      const version = await deps.installed();
      if (!version) { set({ phase: 'idle' }); return; }
      publish({ installed: version });
      const update = pickUpdate(await deps.releases(), version, { assetPrefix: deps.assetPrefix });
      const checkedAt = deps.now();
      await remember({ checkedAt, found: update ?? null });
      set(update ? { phase: 'available', update } : { phase: 'current', checkedAt });
    } catch (error) {
      const reason = failureFrom(error);
      // An automatic look that fails says nothing: the next one tries again.
      if (manual) set({ phase: 'error', step: 'check', reason: reason === 'failed' || reason === 'offline' || reason === 'rate' || reason === 'server' ? reason : 'failed' });
      else set(before.phase === 'checking' ? { phase: 'idle' } : before);
    }
  }

  /** The look the app makes by itself when it opens: only if one is due. */
  async function autoCheck(): Promise<void> {
    await load();
    if (!checkIsDue(memory.checkedAt, deps.now())) {
      // Not due: no look. But learn what is installed so the screen can name it,
      // and bring back the update the last look found, so a restart does not
      // make a waiting update disappear for half a day.
      const version = snapshot.installed || await deps.installed().catch(() => null);
      if (version) {
        if (!snapshot.installed) publish({ installed: version });
        const kept = restoreUpdate(memory.found, version, { assetPrefix: deps.assetPrefix });
        if (kept && snapshot.state.phase === 'idle') set({ phase: 'available', update: kept });
      }
      return;
    }
    await check(false);
  }

  async function proceedToInstall(update: AppUpdate): Promise<void> {
    if (!(await deps.canInstall())) {
      set({ phase: 'permission', update });
      await deps.openInstallSettings();
      return;
    }
    set({ phase: 'installing', update, confirming: false });
    try {
      await deps.install(update.version);
    } catch (error) {
      const reason = failureFrom(error);
      if (reason === 'permission') set({ phase: 'permission', update });
      else set({ phase: 'error', step: 'install', reason: reason === 'cancelled' || reason === 'busy' ? 'failed' : reason, update });
    }
  }

  /** The reader pressed Update (or Try again). */
  async function start(): Promise<void> {
    const state = snapshot.state;
    const update = 'update' in state ? state.update : undefined;
    if (!update || state.phase === 'downloading' || state.phase === 'installing' || state.phase === 'checking') return;
    set({ phase: 'downloading', update, received: 0, total: update.bytes });
    let sha256 = update.sha256;
    if (!sha256 && update.checksumUrl) {
      // A checksum file that cannot be read leaves the signature check as the guard.
      try { sha256 = parseChecksum(await deps.text(update.checksumUrl)); } catch { sha256 = ''; }
    }
    try {
      await deps.download(update, sha256);
    } catch (error) {
      const reason = failureFrom(error);
      if (reason === 'cancelled') set({ phase: 'available', update });
      else if (reason !== 'busy') set({ phase: 'error', step: 'download', reason: reason === 'permission' ? 'failed' : reason, update });
      return;
    }
    await proceedToInstall(update);
  }

  function cancel(): void {
    if (snapshot.state.phase === 'downloading') deps.cancelDownload();
  }

  /** The app came back to the front: continue if the phone's permission page was the reason it left. */
  async function resume(): Promise<void> {
    const state = snapshot.state;
    if (state.phase !== 'permission') return;
    if (await deps.canInstall()) await proceedToInstall(state.update);
  }

  async function dismiss(version: string): Promise<void> {
    publish({ dismissed: version });
    await remember({ dismissed: version });
  }

  return {
    getSnapshot: () => snapshot,
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => { listeners.delete(listener); };
    },
    check,
    autoCheck,
    start,
    cancel,
    resume,
    dismiss,
    dispose() { unsubscribers.forEach((off) => off()); listeners.clear(); },
  };
}

export type Updater = ReturnType<typeof createUpdater>;
