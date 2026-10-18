/**
 * The one store in the app: the reader's install state, the runs, the
 * preferences and the pending screenshot. It persists to AsyncStorage, so a
 * relaunch lands where the user left off.
 *
 * Time is derived, never accumulated. A run records when it started, and the
 * screen it is on reads how far it has got from the clock. One ticker re-renders
 * the tree while anything is live; nothing else updates state per tick, so a
 * slow device cannot lose an update or double-count one.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useState,
} from 'react';

import { advance, plan, slugify, type RunPlan } from './research';
import type { ReaderState, Thread, ThreadView } from './types';

const STORE_KEY = 'kriko.mobile.v1';

export const READER_MODEL = { id: 'kriko-reader-q4', size: '412 MB' };

/** How long the reader takes to install, in milliseconds. */
export const READER_MS = 11000;

export const INITIAL_READER: ReaderState = {
  status: 'absent',
  progress: 0,
  wifiOnly: true,
  modelId: READER_MODEL.id,
  modelSize: READER_MODEL.size,
};

interface State {
  hydrated: boolean;
  reader: ReaderState;
  threads: Thread[];
  /** Whether new questions may read the web by default. */
  web: boolean;
  /**
   * The screenshot waiting to be confirmed on the check screen. Held here rather
   * than passed as a route parameter: a `content://` URI is not safe to
   * round-trip through a URL, and the reader needs it whole.
   */
  pendingShot: string | number | null;
}

type Action =
  | { type: 'hydrate'; state: Partial<State> }
  | { type: 'reader/patch'; patch: Partial<ReaderState> }
  | { type: 'reader/reset' }
  | { type: 'thread/add'; thread: Thread }
  | { type: 'thread/patch'; id: string; patch: Partial<Thread> }
  | { type: 'thread/stop'; id: string; elapsedMs: number }
  | { type: 'thread/remove'; id: string }
  | { type: 'history/clear' }
  | { type: 'shot/set'; shot: string | number | null }
  | { type: 'prefs/patch'; patch: Partial<Pick<State, 'web'>> };

const INITIAL: State = {
  hydrated: false,
  reader: INITIAL_READER,
  threads: [],
  web: true,
  pendingShot: null,
};

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'hydrate':
      return { ...state, ...action.state, hydrated: true };
    case 'reader/patch':
      return { ...state, reader: { ...state.reader, ...action.patch } };
    case 'reader/reset':
      return { ...state, reader: INITIAL_READER };
    case 'thread/add':
      return { ...state, threads: [action.thread, ...state.threads].slice(0, 40) };
    case 'thread/patch':
      return {
        ...state,
        threads: state.threads.map((t) => (t.id === action.id ? { ...t, ...action.patch } : t)),
      };
    case 'thread/stop':
      return {
        ...state,
        threads: state.threads.map((t) =>
          t.id === action.id ? { ...t, status: 'stopped', elapsedMs: action.elapsedMs } : t,
        ),
      };
    case 'thread/remove':
      return { ...state, threads: state.threads.filter((t) => t.id !== action.id) };
    case 'history/clear':
      return { ...state, threads: [] };
    case 'shot/set':
      return { ...state, pendingShot: action.shot };
    case 'prefs/patch':
      return { ...state, ...action.patch };
    default:
      return state;
  }
}

interface Store extends State {
  /** The current time, refreshed while anything is running. */
  now: number;
  readerBusy: boolean;
  readerReady: boolean;
  readerProgress: number;
  startDownload: () => void;
  toggleWifi: () => void;
  reinstallReader: () => void;
  ask: (input: {
    query: string;
    /** Display name for the product, when it differs from the question. */
    title?: string;
    kind?: 'text' | 'screenshot';
    imageUri?: string | number;
    web?: boolean;
  }) => Thread;
  stopRun: (id: string) => void;
  removeThread: (id: string) => void;
  clearHistory: () => void;
  setWeb: (web: boolean) => void;
  setPendingShot: (shot: string | number | null) => void;
  /** The run a screen is showing, with what it had reached. */
  viewOf: (thread: Thread) => ThreadView;
}

const Ctx = createContext<Store | null>(null);

const planCache = new Map<string, RunPlan>();

/** Build (and memoise) the run plan for a thread. */
export function planFor(thread: Pick<Thread, 'query' | 'slug' | 'web'>): RunPlan {
  const key = `${thread.slug}|${thread.query}|${thread.web}`;
  const hit = planCache.get(key);
  if (hit) return hit;
  const built = plan(thread.query, thread.slug, thread.web);
  planCache.set(key, built);
  return built;
}

/** A stored thread plus what the run had reached at `now`. */
export function viewOf(thread: Thread, now: number): ThreadView {
  const total = planFor(thread).totalMs;
  const elapsed =
    thread.status === 'stopped'
      ? thread.elapsedMs
      : Math.min(total, Math.max(0, now - thread.startedAt));
  const partial = advance(planFor(thread), elapsed);
  return {
    ...thread,
    ...partial,
    status: thread.status === 'stopped' ? 'stopped' : partial.status,
  };
}

export function StoreProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, INITIAL);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    let alive = true;
    AsyncStorage.getItem(STORE_KEY)
      .then((raw) => {
        if (!alive) return;
        const saved = raw ? (JSON.parse(raw) as Partial<State>) : {};
        dispatch({
          type: 'hydrate',
          state: {
            reader: { ...INITIAL_READER, ...(saved.reader ?? {}) },
            threads: saved.threads ?? [],
            web: saved.web ?? true,
          },
        });
      })
      .catch(() => dispatch({ type: 'hydrate', state: {} }));
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!state.hydrated) return;
    const { hydrated: _hydrated, pendingShot: _pendingShot, ...rest } = state;
    AsyncStorage.setItem(STORE_KEY, JSON.stringify(rest)).catch(() => {});
  }, [state]);

  const downloading = state.reader.status === 'downloading';
  const running = state.threads.some((t) => t.status === 'searching');

  // One ticker for the whole app, alive only while something is moving.
  useEffect(() => {
    if (!downloading && !running) return;
    const id = setInterval(() => setNow(Date.now()), 100);
    return () => clearInterval(id);
  }, [downloading, running]);

  // Finish the reader once its time is up.
  useEffect(() => {
    if (!downloading) return;
    const startedAt = state.reader.startedAt;
    if (!startedAt) {
      dispatch({ type: 'reader/patch', patch: { startedAt: now } });
      return;
    }
    if (now - startedAt >= READER_MS) {
      dispatch({ type: 'reader/patch', patch: { status: 'ready', progress: 1 } });
    }
  }, [downloading, now, state.reader.startedAt]);

  // Finish any run whose time is up.
  useEffect(() => {
    state.threads.forEach((thread) => {
      if (thread.status !== 'searching') return;
      const total = planFor(thread).totalMs;
      if (now - thread.startedAt >= total) {
        dispatch({ type: 'thread/patch', id: thread.id, patch: { status: 'done', elapsedMs: total } });
      }
    });
  }, [now, state.threads]);

  const startDownload = useCallback(() => {
    dispatch({
      type: 'reader/patch',
      patch: { status: 'downloading', progress: 0, startedAt: Date.now() },
    });
  }, []);

  const toggleWifi = useCallback(() => {
    dispatch({ type: 'reader/patch', patch: { wifiOnly: !state.reader.wifiOnly } });
  }, [state.reader.wifiOnly]);

  const reinstallReader = useCallback(() => dispatch({ type: 'reader/reset' }), []);

  const ask = useCallback<Store['ask']>(({ query, title: given, kind = 'text', imageUri, web }) => {
    const title = (given ?? query).trim() || 'Shared screenshot';
    const slug = slugify(title);
    const thread: Thread = {
      id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`,
      title,
      slug,
      file: `${slug}.sqlite`,
      query: title,
      kind,
      web: web ?? state.web,
      startedAt: Date.now(),
      elapsedMs: 0,
      status: 'searching',
      imageUri,
    };
    dispatch({ type: 'thread/add', thread });
    return thread;
  }, [state.web]);

  const stopRun = useCallback(
    (id: string) => {
      const thread = state.threads.find((t) => t.id === id);
      const elapsed = thread ? Math.min(planFor(thread).totalMs, Date.now() - thread.startedAt) : 0;
      dispatch({ type: 'thread/stop', id, elapsedMs: elapsed });
    },
    [state.threads],
  );

  const removeThread = useCallback((id: string) => dispatch({ type: 'thread/remove', id }), []);
  const clearHistory = useCallback(() => dispatch({ type: 'history/clear' }), []);
  const setWeb = useCallback((web: boolean) => dispatch({ type: 'prefs/patch', patch: { web } }), []);
  const setPendingShot = useCallback(
    (shot: string | number | null) => dispatch({ type: 'shot/set', shot }),
    [],
  );

  const readerProgress =
    state.reader.status === 'ready'
      ? 1
      : state.reader.status === 'downloading' && state.reader.startedAt
        ? Math.max(0, Math.min(1, (now - state.reader.startedAt) / READER_MS))
        : 0;

  const reader = useMemo(
    () => ({ ...state.reader, progress: readerProgress }),
    [state.reader, readerProgress],
  );

  const view = useCallback((thread: Thread) => viewOf(thread, now), [now]);

  const value = useMemo<Store>(
    () => ({
      ...state,
      reader,
      now,
      readerBusy: state.reader.status === 'downloading',
      readerReady: state.reader.status === 'ready',
      readerProgress,
      startDownload,
      toggleWifi,
      reinstallReader,
      ask,
      stopRun,
      removeThread,
      clearHistory,
      setWeb,
      setPendingShot,
      viewOf: view,
    }),
    [
      state,
      reader,
      now,
      readerProgress,
      startDownload,
      toggleWifi,
      reinstallReader,
      ask,
      stopRun,
      removeThread,
      clearHistory,
      setWeb,
      setPendingShot,
      view,
    ],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore(): Store {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useStore must be used inside StoreProvider');
  return ctx;
}

export function useThread(id: string | undefined): ThreadView | null {
  const { threads, viewOf: view } = useStore();
  const found = threads.find((t) => t.id === id);
  return useMemo(() => (found ? view(found) : null), [found, view]);
}
