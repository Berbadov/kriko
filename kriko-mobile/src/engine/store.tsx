/**
 * One store for the app: the keys, the conversations, and the one turn that is
 * allowed to be running.
 *
 * Keys are held in the phone's secure storage and mirrored in memory only while
 * the app is open. Conversations are ordinary JSON in AsyncStorage; nothing in
 * them is a secret, and the provider keys never enter that file.
 *
 * A turn is asked to stop through an AbortController. When it stops, whatever
 * it had is what the message keeps: partial text, the searches it ran, and the
 * pages it read. Nothing is invented after the fact.
 */

import AsyncStorage from '@react-native-async-storage/async-storage';
import * as SecureStore from 'expo-secure-store';
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  useRef,
} from 'react';

import { runTurn, readListing } from './providers';
import { readingTitle, SCREENSHOT_QUESTION, type AnswerStyle } from './prompt';
import { hasTrialBundle, openAccess, openTrial, type TrialAccess } from './sharekeys';
import { setLanguage, type Language } from '../i18n';
import { drainQueue } from './queue';
import { restoreScanThreads, withoutScanThreads } from './types';
import type {
  AccessState,
  Message,
  ProviderKeys,
  QueueJob,
  ResearchMode,
  Reading,
  Source,
  Step,
  Thread,
} from './types';

const THREADS_KEY = 'kriko.agent.threads.v1';
const TRIAL_KEY = 'kriko.agent.trial.v1';
const KEYS_KEY = 'kriko.agent.keys.v1';
const PREFS_KEY = 'kriko.agent.prefs.v1';
const QUEUE_KEY = 'kriko.agent.scan-queue.v1';

const EMPTY_ACCESS: AccessState = { kind: 'none', label: '', left: 0, limit: 0 };

interface PendingStorageWrite {
  pending: string | null;
  writing: boolean;
}

function persistLatest(ref: { current: PendingStorageWrite }, key: string, payload: string): void {
  ref.current.pending = payload;
  if (ref.current.writing) return;
  ref.current.writing = true;
  void (async () => {
    while (ref.current.pending !== null) {
      const next = ref.current.pending;
      ref.current.pending = null;
      await AsyncStorage.setItem(key, next).catch(() => {});
    }
    ref.current.writing = false;
  })();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

function safeTime(value: unknown, fallback = Date.now()): number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : fallback;
}

function normalizeReading(value: unknown): Reading | null {
  if (!isRecord(value)) return null;
  const string = (key: string, max = 900) =>
    typeof value[key] === 'string' ? (value[key] as string).slice(0, max) : '';
  return {
    brand: string('brand', 80),
    product: string('product', 160),
    model: string('model', 80),
    price: string('price', 40),
    condition: string('condition', 20) || 'unknown',
    detail: string('detail'),
    note: string('note', 240),
    site: string('site', 120) || undefined,
    url: string('url', 2048) || undefined,
  };
}

function normalizeThread(value: unknown): Thread | null {
  if (!isRecord(value) || typeof value.id !== 'string' || !Array.isArray(value.messages)) return null;
  const createdAt = safeTime(value.createdAt);
  const messages: Message[] = value.messages.flatMap((raw): Message[] => {
    if (!isRecord(raw) || (raw.role !== 'user' && raw.role !== 'assistant')) return [];
    const reading = raw.reading === undefined ? undefined : normalizeReading(raw.reading) ?? undefined;
    const sources: Source[] = Array.isArray(raw.sources)
      ? raw.sources.filter((row): row is Source =>
          isRecord(row) && typeof row.n === 'number' && Number.isFinite(row.n) &&
          typeof row.url === 'string' && typeof row.title === 'string' && typeof row.host === 'string',
        )
      : [];
    const validKinds = ['search', 'fetch', 'note', 'error'];
    const steps: Step[] = Array.isArray(raw.steps)
      ? raw.steps.filter((row): row is Step =>
          isRecord(row) && typeof row.id === 'string' && validKinds.includes(String(row.kind)) &&
          typeof row.text === 'string' && typeof row.at === 'number' && Number.isFinite(row.at),
        )
      : [];
    return [{
      id: typeof raw.id === 'string' ? raw.id : `${value.id}-${messages.length}`,
      role: raw.role,
      text: typeof raw.text === 'string' ? raw.text : '',
      createdAt: safeTime(raw.createdAt, createdAt),
      steps,
      sources,
      reading,
      imageUri: typeof raw.imageUri === 'string' ? raw.imageUri : undefined,
      pending: raw.pending === true,
      stopped: raw.stopped === true,
      error: typeof raw.error === 'string' ? raw.error : undefined,
      unverified: raw.unverified === true,
    }];
  });
  return {
    id: value.id,
    title: typeof value.title === 'string' ? value.title : 'Product scan',
    createdAt,
    updatedAt: Math.max(createdAt, safeTime(value.updatedAt, createdAt)),
    messages,
  };
}

function normalizeQueueJob(value: unknown): QueueJob | null {
  if (!isRecord(value) || typeof value.id !== 'string' || typeof value.question !== 'string') return null;
  const statuses = ['queued', 'running', 'done', 'error', 'cancelled'] as const;
  if (!statuses.includes(value.status as (typeof statuses)[number])) return null;
  const reading = normalizeReading(value.reading);
  if (!reading) return null;
  const createdAt = safeTime(value.createdAt);
  const sources = Array.isArray(value.sources)
    ? value.sources.filter((row): row is Source =>
        isRecord(row) && typeof row.n === 'number' && Number.isFinite(row.n) &&
        typeof row.url === 'string' && typeof row.title === 'string' && typeof row.host === 'string',
      )
    : [];
  const validKinds = ['search', 'fetch', 'note', 'error'];
  const steps: Step[] = Array.isArray(value.steps)
    ? value.steps.filter((row): row is Step =>
        isRecord(row) && typeof row.id === 'string' && validKinds.includes(String(row.kind)) &&
        typeof row.text === 'string' && typeof row.at === 'number' && Number.isFinite(row.at),
      )
    : [];
  return {
    id: value.id,
    question: value.question,
    researchMode: value.researchMode === 'site_reviews' ? 'site_reviews' : value.researchMode === 'research' ? 'research' : undefined,
    reviewSite: typeof value.reviewSite === 'string' ? value.reviewSite : undefined,
    reading,
    imageUri: typeof value.imageUri === 'string' ? value.imageUri : undefined,
    status: value.status as QueueJob['status'],
    text: typeof value.text === 'string' ? value.text : '',
    sources,
    steps,
    error: typeof value.error === 'string' ? value.error : undefined,
    threadId: typeof value.threadId === 'string' ? value.threadId : undefined,
    answerId: typeof value.answerId === 'string' ? value.answerId : undefined,
    createdAt,
    updatedAt: Math.max(createdAt, safeTime(value.updatedAt, createdAt)),
  };
}

interface Prefs {
  thoroughness: number;
  answerStyle: AnswerStyle;
  language: Language;
}

const INITIAL_PREFS: Prefs = { thoroughness: 50, answerStyle: 'standard', language: 'en' };

interface State extends Prefs {
  hydrated: boolean;
  access: AccessState;
  threads: Thread[];
  activeId: string | null;
  streamingId: string | null;
  queueJobs: QueueJob[];
  runnerVersion: number;
  trialUsed: number;
}

type Action =
  | {
      type: 'hydrate';
      access: AccessState;
      threads: Thread[];
      activeId: string | null;
      trialUsed: number;
      prefs: Prefs;
      queueJobs: QueueJob[];
    }
  | { type: 'prefs/patch'; patch: Partial<Prefs> }
  | { type: 'access/set'; access: AccessState }
  | { type: 'thread/add'; thread: Thread }
  | { type: 'thread/addBackground'; thread: Thread }
  | { type: 'thread/patch'; id: string; patch: Partial<Thread> }
  | { type: 'thread/remove'; id: string }
  | { type: 'threads/clear' }
  | { type: 'active/set'; id: string | null }
  | { type: 'streaming/set'; id: string | null }
  | { type: 'runner/idle' }
  | { type: 'queue/add'; job: QueueJob }
  | { type: 'queue/patch'; id: string; patch: Partial<QueueJob> }
  | { type: 'queue/appendText'; id: string; delta: string }
  | { type: 'queue/appendStep'; id: string; step: Step }
  | { type: 'queue/remove'; id: string }
  | { type: 'message/add'; threadId: string; message: Message }
  | { type: 'message/patch'; threadId: string; messageId: string; patch: Partial<Message> }
  | { type: 'message/appendText'; threadId: string; messageId: string; delta: string }
  | { type: 'message/clearText'; threadId: string; messageId: string }
  | { type: 'message/appendStep'; threadId: string; messageId: string; step: Step }
  | { type: 'trial/use' }
  | { type: 'trial/refund' };

function capThreads(threads: Thread[]): Thread[] {
  return threads.slice(0, 20).map((thread) => ({
    ...thread,
    messages: thread.messages.slice(-40),
  }));
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'hydrate':
      return {
        ...state,
        ...action.prefs,
        hydrated: true,
        access: action.access,
        threads: action.threads,
        activeId: action.activeId,
        trialUsed: action.trialUsed,
        queueJobs: action.queueJobs,
      };
    case 'prefs/patch':
      return { ...state, ...action.patch };
    case 'access/set':
      return { ...state, access: action.access };
    case 'thread/add':
      return {
        ...state,
        threads: capThreads([action.thread, ...state.threads]),
        activeId: action.thread.id,
      };
    case 'thread/addBackground':
      return { ...state, threads: capThreads([action.thread, ...state.threads]) };
    case 'thread/patch':
      return {
        ...state,
        threads: state.threads.map((thread) =>
          thread.id === action.id ? { ...thread, ...action.patch, updatedAt: Date.now() } : thread,
        ),
      };
    case 'thread/remove':
      return {
        ...state,
        threads: state.threads.filter((thread) => thread.id !== action.id),
        queueJobs: withoutScanThreads(state.queueJobs, new Set([action.id])),
        activeId: state.activeId === action.id ? null : state.activeId,
      };
    case 'threads/clear':
      return { ...state, threads: [], queueJobs: [], activeId: null };
    case 'active/set':
      return { ...state, activeId: action.id };
    case 'streaming/set':
      return { ...state, streamingId: action.id };
    case 'runner/idle':
      return { ...state, runnerVersion: state.runnerVersion + 1 };
    case 'queue/add':
      return { ...state, queueJobs: [...state.queueJobs, action.job].slice(-50) };
    case 'queue/patch':
      return {
        ...state,
        queueJobs: state.queueJobs.map((job) =>
          job.id === action.id ? { ...job, ...action.patch, updatedAt: Date.now() } : job,
        ),
      };
    case 'queue/appendStep':
      return { ...state, queueJobs: state.queueJobs.map((job) => job.id === action.id
        ? { ...job, steps: [...(job.steps ?? []), action.step].slice(-40), updatedAt: Date.now() }
        : job) };
    case 'queue/appendText':
      return {
        ...state,
        queueJobs: state.queueJobs.map((job) =>
          job.id === action.id
            ? { ...job, text: `${job.text}${action.delta}`, updatedAt: Date.now() }
            : job,
        ),
      };
    case 'queue/remove':
      return { ...state, queueJobs: state.queueJobs.filter((job) => job.id !== action.id) };
    case 'message/add':
      return {
        ...state,
        threads: state.threads.map((thread) =>
          thread.id === action.threadId
            ? { ...thread, messages: [...thread.messages, action.message], updatedAt: Date.now() }
            : thread,
        ),
      };
    case 'message/patch':
      return {
        ...state,
        threads: state.threads.map((thread) =>
          thread.id === action.threadId
            ? {
                ...thread,
                updatedAt: Date.now(),
                messages: thread.messages.map((message) =>
                  message.id === action.messageId ? { ...message, ...action.patch } : message,
                ),
              }
            : thread,
        ),
      };
    case 'message/appendText':
      return {
        ...state,
        threads: state.threads.map((thread) =>
          thread.id === action.threadId
            ? {
                ...thread,
                updatedAt: Date.now(),
                messages: thread.messages.map((message) =>
                  message.id === action.messageId
                    ? { ...message, text: `${message.text}${action.delta}` }
                    : message,
                ),
              }
            : thread,
        ),
      };
    case 'message/clearText':
      return {
        ...state,
        threads: state.threads.map((thread) =>
          thread.id === action.threadId
            ? {
                ...thread,
                messages: thread.messages.map((message) =>
                  message.id === action.messageId ? { ...message, text: '' } : message,
                ),
              }
            : thread,
        ),
      };
    case 'message/appendStep':
      return {
        ...state,
        threads: state.threads.map((thread) =>
          thread.id === action.threadId
            ? {
                ...thread,
                updatedAt: Date.now(),
                messages: thread.messages.map((message) =>
                  message.id === action.messageId
                    ? { ...message, steps: [...(message.steps ?? []), action.step] }
                    : message,
                ),
              }
            : thread,
        ),
      };
    case 'trial/use':
      return {
        ...state,
        trialUsed: state.trialUsed + 1,
        access: {
          ...state.access,
          left: Math.max(0, state.access.left - 1),
        },
      };
    case 'trial/refund':
      return {
        ...state,
        trialUsed: Math.max(0, state.trialUsed - 1),
        access:
          state.access.kind === 'trial'
            ? { ...state.access, left: state.access.left + 1 }
            : state.access,
      };
    default:
      return state;
  }
}

export class AccessError extends Error {
  code: 'none' | 'exhausted';

  constructor(code: 'none' | 'exhausted', message: string) {
    super(message);
    this.name = 'AccessError';
    this.code = code;
  }
}

function newId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

function titleFor(text: string, reading?: Reading | null): string {
  const named = reading ? readingTitle(reading) : '';
  const base = named || text.trim() || 'Screenshot';
  return base.length > 64 ? `${base.slice(0, 61)}…` : base;
}

interface Store extends State {
  activeThread: Thread | null;
  streaming: boolean;
  trialLeft: number;
  /** True when a question can be sent without asking for an access code. */
  canAsk: boolean;
  newChat: () => void;
  openThread: (id: string) => void;
  openScanResult: (jobId: string) => void;
  send: (text: string, options?: { reading?: Reading; imageUri?: string }) => Promise<void>;
  stop: () => void;
  readShot: (base64: string, mime: string, signal?: AbortSignal) => Promise<Reading>;
  enqueueScan: (
    reading: Reading,
    imageUri?: string,
    question?: string,
    options?: { researchMode?: ResearchMode; reviewSite?: string },
  ) => string;
  cancelQueue: (id: string) => void;
  unlock: (code: string, password: string, label: string) => Promise<void>;
  saveOwnKeys: (mercury: string, deepseek: string) => Promise<void>;
  forgetAccess: () => Promise<void>;
  deleteThread: (id: string) => void;
  clearHistory: () => void;
  setThoroughness: (value: number) => void;
  setAnswerStyle: (value: AnswerStyle) => void;
  setAppLanguage: (value: Language) => void;
}

const Ctx = createContext<Store | null>(null);

interface HeldKeys {
  keys: ProviderKeys;
  source: 'shared' | 'own' | 'trial';
  label: string;
  /** The trial's ceiling, carried so a saved trial keeps its own number. */
  limit?: number;
}

export function StoreProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, {
    ...INITIAL_PREFS,
    hydrated: false,
    access: EMPTY_ACCESS,
    threads: [],
    activeId: null,
    streamingId: null,
    queueJobs: [],
    runnerVersion: 0,
    trialUsed: 0,
  });

  const held = useRef<HeldKeys | null>(null);
  const trial = useRef<TrialAccess | null>(null);
  const abort = useRef<AbortController | null>(null);
  const queueAbort = useRef<AbortController | null>(null);
  const runningQueueId = useRef<string | null>(null);
  const cancelledQueueIds = useRef(new Set<string>());
  const sending = useRef(false);
  const idleWaiters = useRef<(() => void)[]>([]);
  const stateRef = useRef(state);
  const mounted = useRef(true);
  const threadWrite = useRef<PendingStorageWrite>({ pending: null, writing: false });
  const queueWrite = useRef<PendingStorageWrite>({ pending: null, writing: false });

  const releaseSendLock = useCallback(() => {
    sending.current = false;
    for (const resolve of idleWaiters.current.splice(0)) resolve();
    if (mounted.current) dispatch({ type: 'runner/idle' });
  }, []);

  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  useEffect(() => {
    const waiters = idleWaiters.current;
    mounted.current = true;
    return () => {
      mounted.current = false;
      abort.current?.abort();
      queueAbort.current?.abort();
      sending.current = false;
      for (const resolve of waiters.splice(0)) resolve();
    };
  }, []);

  useEffect(() => {
    let alive = true;
    (async () => {
      let threads: Thread[] = [];
      let activeId: string | null = null;
      let trialUsed = 0;
      let queueJobs: QueueJob[] = [];
      let access: AccessState = EMPTY_ACCESS;
      let prefs: Prefs = INITIAL_PREFS;

      try {
        const [saved, used, keysRaw, prefsRaw, queueRaw] = await Promise.all([
          AsyncStorage.getItem(THREADS_KEY).catch(() => null),
          AsyncStorage.getItem(TRIAL_KEY).catch(() => null),
          SecureStore.getItemAsync(KEYS_KEY).catch(() => null),
          AsyncStorage.getItem(PREFS_KEY).catch(() => null),
          AsyncStorage.getItem(QUEUE_KEY).catch(() => null),
        ]);
        if (prefsRaw) {
          try {
            const stored = JSON.parse(prefsRaw) as Partial<Prefs>;
            const level = Number(stored.thoroughness);
            prefs = {
              thoroughness: Number.isFinite(level) ? Math.max(0, Math.min(100, level)) : 50,
              answerStyle:
                stored.answerStyle === 'short' || stored.answerStyle === 'standard' || stored.answerStyle === 'product'
                  ? stored.answerStyle
                  : 'standard',
              language: stored.language === 'tr' ? 'tr' : 'en',
            };
          } catch {
            prefs = INITIAL_PREFS;
          }
        }
        if (queueRaw) {
          try {
            const savedQueue = JSON.parse(queueRaw) as unknown;
            if (Array.isArray(savedQueue)) {
              queueJobs = savedQueue
                .map(normalizeQueueJob)
                .filter((job): job is QueueJob => job !== null)
                .slice(-50)
                .map((job) => ({
                  ...job,
                  ...(job.status === 'running'
                    ? {
                        status: 'error' as const,
                        error: 'Kriko closed before this scan finished. Scan this product again.',
                        updatedAt: Date.now(),
                      }
                    : {}),
                }));
            }
          } catch {
            // A damaged queue should not make otherwise valid conversations disappear.
            queueJobs = [];
          }
        }
        setLanguage(prefs.language);
        if (saved) {
          try {
            const parsed = JSON.parse(saved) as {
              threads?: unknown[];
              activeId?: string | null;
            };
            if (Array.isArray(parsed.threads)) {
              threads = parsed.threads
                .map(normalizeThread)
                .filter((thread): thread is Thread => thread !== null);
            }
            if (typeof parsed.activeId === 'string') activeId = parsed.activeId;
          } catch {
            threads = [];
            activeId = null;
          }
        }
        if (used) {
          const value = Number(used);
          if (Number.isFinite(value)) trialUsed = Math.max(0, Math.floor(value));
        }
        if (keysRaw) {
          const stored = JSON.parse(keysRaw) as {
            mercury?: string;
            deepseek?: string;
            source?: string;
            label?: string;
            limit?: number;
          };
          if (stored.mercury && stored.deepseek) {
            const source =
              stored.source === 'own'
                ? 'own'
                : stored.source === 'trial'
                  ? 'trial'
                  : 'shared';
            const storedLimit = Number(stored.limit);
            const limit =
              Number.isFinite(storedLimit) && storedLimit > 0 ? storedLimit : undefined;
            held.current = {
              keys: { mercury: stored.mercury, deepseek: stored.deepseek },
              source,
              label: stored.label ?? '',
              limit,
            };
            if (source === 'trial') {
              const trialLimit = limit ?? 10;
              trial.current = { keys: held.current.keys, limit: trialLimit };
              access = {
                kind: 'trial',
                label: '',
                left: Math.max(0, trialLimit - trialUsed),
                limit: trialLimit,
              };
            } else {
              access = {
                kind: source,
                label: held.current.label,
                left: 0,
                limit: 0,
              };
            }
          }
        }
      } catch {
        // A corrupt store is an empty app, not a crash.
      }

      // Persisted threads can contain a pending assistant turn if Android
      // stopped the process. Keep that visible as interrupted, never spinning.
      threads = threads.map((thread) => ({
        ...thread,
        messages: thread.messages.map((message) => message.pending
          ? {
              ...message,
              pending: false,
              error: message.error || 'Kriko closed before this answer finished. Ask again to retry.',
            }
          : message),
      }));
      threads = restoreScanThreads(threads, queueJobs);

      if (!held.current && hasTrialBundle()) {
        const opened = openTrial();
        if (opened) {
          trial.current = opened;
          // Keep the opened trial in secure storage: scrypt is deliberately
          // expensive, and paying it on every launch is a cold start nobody
          // asked for. The count still lives in AsyncStorage and is not a wall.
          held.current = {
            keys: opened.keys,
            source: 'trial',
            label: 'Free trial',
            limit: opened.limit,
          };
          void SecureStore.setItemAsync(
            KEYS_KEY,
            JSON.stringify({
              ...opened.keys,
              source: 'trial',
              label: 'Free trial',
              limit: opened.limit,
            }),
          ).catch(() => {});
          const left = Math.max(0, opened.limit - trialUsed);
          // Even at zero, the app stays on the chat: the history and settings
          // must remain reachable, and the composer is where the code goes.
          access = { kind: 'trial', label: '', left, limit: opened.limit };
        }
      }

      if (!alive) return;
      dispatch({
        type: 'hydrate',
        access,
        threads: capThreads(threads),
        activeId: threads.some((thread) => thread.id === activeId) ? activeId : null,
        trialUsed,
        prefs,
        queueJobs,
      });
    })();
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!state.hydrated) return;
    const payload = JSON.stringify({
      threads: capThreads(state.threads),
      activeId: state.activeId,
    });
    persistLatest(threadWrite, THREADS_KEY, payload);
  }, [state.threads, state.activeId, state.hydrated]);

  useEffect(() => {
    if (!state.hydrated) return;
    persistLatest(queueWrite, QUEUE_KEY, JSON.stringify(state.queueJobs.slice(-50)));
  }, [state.queueJobs, state.hydrated]);

  useEffect(() => {
    if (!state.hydrated) return;
    AsyncStorage.setItem(TRIAL_KEY, String(state.trialUsed)).catch(() => {});
  }, [state.trialUsed, state.hydrated]);

  useEffect(() => {
    if (!state.hydrated) return;
    const prefs: Prefs = {
      thoroughness: state.thoroughness,
      answerStyle: state.answerStyle,
      language: state.language,
    };
    AsyncStorage.setItem(PREFS_KEY, JSON.stringify(prefs)).catch(() => {});
  }, [state.thoroughness, state.answerStyle, state.language, state.hydrated]);

  const keysForTurn = useCallback(async (): Promise<ProviderKeys> => {
    const heldNow = held.current;
    if (heldNow && heldNow.source !== 'trial') return heldNow.keys;
    if (heldNow?.source === 'trial') {
      const limit = heldNow.limit ?? trial.current?.limit ?? 10;
      if (stateRef.current.access.left <= 0) {
        throw new AccessError(
          'exhausted',
          `The ${limit} free questions on this phone are used up. Paste an access code to keep going.`,
        );
      }
      dispatch({ type: 'trial/use' });
      return heldNow.keys;
    }
    if (trial.current) {
      const left = stateRef.current.access.left;
      if (left <= 0) {
        throw new AccessError(
          'exhausted',
          `The ${trial.current.limit} free questions on this phone are used up. Paste an access code to keep going.`,
        );
      }
      dispatch({ type: 'trial/use' });
      return trial.current.keys;
    }
    if (hasTrialBundle() && !trial.current) {
      const opened = openTrial();
      if (opened) {
        trial.current = opened;
        const left = Math.max(0, opened.limit - stateRef.current.trialUsed);
        if (left > 0) {
          dispatch({ type: 'trial/use' });
          return opened.keys;
        }
      }
    }
    throw new AccessError('none', 'No keys on this phone yet. Paste an access code, or add your own keys.');
  }, []);

  /** A screenshot read spends the owner's vision key but not a trial question. */
  const keysForVision = useCallback(async (): Promise<ProviderKeys> => {
    if (held.current) return held.current.keys;
    if (!trial.current && hasTrialBundle()) trial.current = openTrial();
    if (trial.current) {
      if (stateRef.current.access.kind === 'trial' && stateRef.current.access.left <= 0) {
        throw new AccessError(
          'exhausted',
          'The free questions on this phone are used up. Paste an access code to keep reading screenshots.',
        );
      }
      return trial.current.keys;
    }
    throw new AccessError('none', 'No keys on this phone yet. Paste an access code, or add your own keys.');
  }, []);

  const send = useCallback<Store['send']>(
    async (text, options) => {
      const asked = text.trim();
      const reading = options?.reading;
      if (!asked && !reading) return;
      while (sending.current) {
        await new Promise<void>((resolve) => idleWaiters.current.push(resolve));
      }
      if (!mounted.current || stateRef.current.streamingId) return;
      // React state updates after a render; this ref closes the gap while keys
      // are being loaded so two rapid taps cannot start and charge two turns.
      sending.current = true;
      const trialTurn = stateRef.current.access.kind === 'trial';
      let charged = false;
      let keys: ProviderKeys;
      try {
        keys = await keysForTurn();
      } catch (error) {
        releaseSendLock();
        throw error;
      }
      charged = trialTurn;

      const now = Date.now();
      const currentId = stateRef.current.activeId;
      const existing = stateRef.current.threads.find((thread) => thread.id === currentId);
      const threadId = existing?.id ?? newId('t');
      const title = titleFor(asked, reading);

      if (!existing) {
        dispatch({
          type: 'thread/add',
          thread: {
            id: threadId,
            title,
            createdAt: now,
            updatedAt: now,
            messages: [],
          },
        });
      } else if (existing.messages.length === 0) {
        dispatch({ type: 'thread/patch', id: threadId, patch: { title } });
      }

      const userMessage: Message = {
        id: newId('m'),
        role: 'user',
        text: asked || 'What should I know about this product?',
        createdAt: now,
        reading,
        imageUri: options?.imageUri,
      };
      const answer: Message = {
        id: newId('m'),
        role: 'assistant',
        text: '',
        createdAt: now + 1,
        pending: true,
        steps: [],
        sources: [],
      };

      dispatch({ type: 'message/add', threadId, message: userMessage });
      dispatch({ type: 'message/add', threadId, message: answer });
      dispatch({ type: 'active/set', id: threadId });
      dispatch({ type: 'streaming/set', id: threadId });

      // The history is what the thread held before this question. The store's
      // own state may not have rendered yet, so it is read from the reducer's
      // snapshot and the new messages are not part of it.
      const history = (existing?.messages ?? []).filter((message) => !message.pending);

      const controller = new AbortController();
      abort.current = controller;
      const answerId = answer.id;

      try {
        const result = await runTurn({
          keys,
          history,
          question: asked,
          reading,
          signal: controller.signal,
          thoroughness: stateRef.current.thoroughness,
          answerStyle: stateRef.current.answerStyle,
          language: stateRef.current.language,
          onText: (delta) => {
            dispatch({
              type: 'message/appendText',
              threadId,
              messageId: answerId,
              delta,
            });
          },
          onDiscardText: () => {
            dispatch({
              type: 'message/clearText',
              threadId,
              messageId: answerId,
            });
          },
          onStep: (kind, line) => {
            dispatch({
              type: 'message/appendStep',
              threadId,
              messageId: answerId,
              step: { id: newId('s'), kind, text: line, at: Date.now() },
            });
          },
          onSources: (sources) => {
            dispatch({
              type: 'message/patch',
              threadId,
              messageId: answerId,
              patch: { sources },
            });
          },
        });

        const patch: Partial<Message> = {
          steps: result.steps,
          sources: result.sources,
          actions: result.actions,
          pending: false,
          stopped: result.stopped,
          unverified: result.unverified,
          error: result.error || undefined,
        };
        if (result.text) patch.text = result.text;
        // A failed provider call is not a question the reader got to ask.
        if (charged && result.error && !result.text && !result.stopped) {
          dispatch({ type: 'trial/refund' });
        }
        dispatch({
          type: 'message/patch',
          threadId,
          messageId: answerId,
          patch,
        });
      } catch (error) {
        if (charged) dispatch({ type: 'trial/refund' });
        dispatch({
          type: 'message/patch',
          threadId,
          messageId: answerId,
          patch: {
            pending: false,
            error:
              error instanceof AccessError
                ? error.message
                : error instanceof Error
                  ? error.message
                  : 'The turn failed.',
          },
        });
      } finally {
        abort.current = null;
        dispatch({ type: 'streaming/set', id: null });
        releaseSendLock();
      }
    },
    [keysForTurn, releaseSendLock],
  );

  const stop = useCallback(() => {
    abort.current?.abort();
  }, []);

  const readShot = useCallback(
    async (base64: string, mime: string, signal?: AbortSignal): Promise<Reading> => {
      const keys = await keysForVision();
      return readListing(base64, mime, keys.deepseek, signal);
    },
    [keysForVision],
  );

  const enqueueScan = useCallback<Store['enqueueScan']>((reading, imageUri, question, options) => {
    const id = newId('q');
    const now = Date.now();
    dispatch({
      type: 'queue/add',
      job: {
        id,
        question: question?.trim() || SCREENSHOT_QUESTION,
        researchMode: options?.researchMode,
        reviewSite: options?.reviewSite,
        reading,
        imageUri,
        status: 'queued',
        text: '',
        sources: [],
        steps: [],
        createdAt: now,
        updatedAt: now,
      },
    });
    return id;
  }, []);

  const cancelQueue = useCallback((id: string) => {
    cancelledQueueIds.current.add(id);
    const job = stateRef.current.queueJobs.find((item) => item.id === id);
    if (!job || job.status === 'done' || job.status === 'error' || job.status === 'cancelled') {
      cancelledQueueIds.current.delete(id);
      return;
    }
    if (runningQueueId.current === id) {
      queueAbort.current?.abort();
      return;
    }
    dispatch({ type: 'queue/patch', id, patch: { status: 'cancelled' } });
  }, []);

  useEffect(() => {
    if (!state.hydrated || state.streamingId || sending.current) return;
    const jobs = state.queueJobs.filter((item) => item.status === 'queued');
    if (!jobs.length) return;

    sending.current = true;
    void drainQueue(jobs, async (job) => {
      if (cancelledQueueIds.current.has(job.id)) return;
      runningQueueId.current = job.id;
      const controller = new AbortController();
      queueAbort.current = controller;
      dispatch({ type: 'queue/patch', id: job.id, patch: { status: 'running' } });
      let charged = false;
      let threadId = '';
      let answerId = '';
      try {
        const trialTurn = stateRef.current.access.kind === 'trial';
        const keys = await keysForTurn();
        charged = trialTurn;
        if (controller.signal.aborted || cancelledQueueIds.current.has(job.id)) {
          if (charged) dispatch({ type: 'trial/refund' });
          charged = false;
          return;
        }

        const now = Date.now();
        threadId = newId('t');
        const title = titleFor('', job.reading);
        const userMessage: Message = {
          id: newId('m'),
          role: 'user',
          text: job.question,
          createdAt: now,
          reading: job.reading,
          imageUri: job.imageUri,
        };
        const answer: Message = {
          id: newId('m'),
          role: 'assistant',
          text: '',
          createdAt: now + 1,
          pending: true,
          steps: [],
          sources: [],
        };
        answerId = answer.id;
        dispatch({
          type: 'thread/addBackground',
          thread: { id: threadId, title, createdAt: now, updatedAt: now, messages: [userMessage, answer] },
        });
        dispatch({ type: 'queue/patch', id: job.id, patch: { threadId, answerId: answer.id } });

        const result = await runTurn({
          keys,
          history: [],
          question: job.question,
          reading: job.reading,
          researchMode: job.researchMode,
          reviewSite: job.reviewSite,
          signal: controller.signal,
          thoroughness: stateRef.current.thoroughness,
          answerStyle: stateRef.current.answerStyle,
          language: stateRef.current.language,
          onText: (delta) => {
            dispatch({ type: 'queue/appendText', id: job.id, delta });
            dispatch({ type: 'message/appendText', threadId, messageId: answer.id, delta });
          },
          onDiscardText: () => {
            dispatch({ type: 'queue/patch', id: job.id, patch: { text: '' } });
            dispatch({ type: 'message/clearText', threadId, messageId: answer.id });
          },
          onStep: (kind, line) => {
            const step: Step = { id: newId('s'), kind, text: line, at: Date.now() };
            dispatch({ type: 'queue/appendStep', id: job.id, step });
            dispatch({ type: 'message/appendStep', threadId, messageId: answer.id, step });
          },
          onSources: (sources) => {
            dispatch({ type: 'queue/patch', id: job.id, patch: { sources } });
            dispatch({ type: 'message/patch', threadId, messageId: answer.id, patch: { sources } });
          },
        });

        if (charged && result.error && !result.text && !result.stopped) {
          dispatch({ type: 'trial/refund' });
        }
        dispatch({
          type: 'queue/patch',
          id: job.id,
          patch: {
            status: result.stopped ? 'cancelled' : result.error ? 'error' : 'done',
            text: result.text,
            sources: result.sources,
            steps: result.steps,
            error: result.error || undefined,
          },
        });
        dispatch({
          type: 'message/patch',
          threadId,
          messageId: answer.id,
          patch: {
            text: result.text,
            steps: result.steps,
            sources: result.sources,
            actions: result.actions,
            pending: false,
            stopped: result.stopped,
            unverified: result.unverified,
            error: result.error || undefined,
          },
        });
      } catch (error) {
        if (charged) dispatch({ type: 'trial/refund' });
        const message = error instanceof Error ? error.message : 'The queued scan failed.';
        dispatch({
          type: 'queue/patch',
          id: job.id,
          patch: { status: controller.signal.aborted ? 'cancelled' : 'error', error: message },
        });
        if (threadId && answerId) {
          dispatch({
            type: 'message/patch',
            threadId,
            messageId: answerId,
            patch: { pending: false, error: message, stopped: controller.signal.aborted },
          });
        }
      } finally {
        runningQueueId.current = null;
        queueAbort.current = null;
        cancelledQueueIds.current.delete(job.id);
      }
    }, (id) => {
      if (!mounted.current) return true;
      const cancelled = cancelledQueueIds.current.has(id);
      if (cancelled && runningQueueId.current !== id) cancelledQueueIds.current.delete(id);
      return cancelled;
    }).finally(releaseSendLock);
  }, [state.hydrated, state.queueJobs, state.streamingId, state.runnerVersion, keysForTurn, releaseSendLock]);

  const unlock = useCallback(async (code: string, password: string, label: string) => {
    const keys = openAccess(code, password);
    await SecureStore.setItemAsync(
      KEYS_KEY,
      JSON.stringify({ ...keys, source: 'shared', label }),
    );
    held.current = { keys, source: 'shared', label };
    dispatch({
      type: 'access/set',
      access: { kind: 'shared', label, left: 0, limit: 0 },
    });
  }, []);

  const saveOwnKeys = useCallback(async (mercury: string, deepseek: string) => {
    const keys = { mercury: mercury.trim(), deepseek: deepseek.trim() };
    if (!keys.mercury || !keys.deepseek) {
      throw new Error('Both keys are needed: Mercury runs the agent, DeepSeek runs the search.');
    }
    await SecureStore.setItemAsync(
      KEYS_KEY,
      JSON.stringify({ ...keys, source: 'own', label: 'Your own keys' }),
    );
    held.current = { keys, source: 'own', label: 'Your own keys' };
    dispatch({
      type: 'access/set',
      access: { kind: 'own', label: 'Your own keys', left: 0, limit: 0 },
    });
  }, []);

  const forgetAccess = useCallback(async () => {
    await SecureStore.deleteItemAsync(KEYS_KEY);
    held.current = null;
    let opened = trial.current;
    if (!opened && hasTrialBundle()) opened = openTrial();
    if (opened) {
      trial.current = opened;
      const used = stateRef.current.trialUsed;
      const left = Math.max(0, opened.limit - used);
      void SecureStore.setItemAsync(
        KEYS_KEY,
        JSON.stringify({
          ...opened.keys,
          source: 'trial',
          label: 'Free trial',
          limit: opened.limit,
        }),
      ).catch(() => {});
      dispatch({
        type: 'access/set',
        access: { kind: 'trial', label: '', left, limit: opened.limit },
      });
      return;
    }
    dispatch({ type: 'access/set', access: EMPTY_ACCESS });
  }, []);

  const newChat = useCallback(() => dispatch({ type: 'active/set', id: null }), []);
  const setThoroughness = useCallback(
    (value: number) =>
      dispatch({ type: 'prefs/patch', patch: { thoroughness: Math.max(0, Math.min(100, value)) } }),
    [],
  );
  const setAnswerStyle = useCallback(
    (value: AnswerStyle) => dispatch({ type: 'prefs/patch', patch: { answerStyle: value } }),
    [],
  );
  const setAppLanguage = useCallback((value: Language) => {
    setLanguage(value);
    dispatch({ type: 'prefs/patch', patch: { language: value } });
  }, []);
  const openThread = useCallback((id: string) => dispatch({ type: 'active/set', id }), []);
  const openScanResult = useCallback((jobId: string) => {
    const job = stateRef.current.queueJobs.find((item) => item.id === jobId);
    if (!job?.threadId) return;
    if (!stateRef.current.threads.some((thread) => thread.id === job.threadId)) {
      const restored = restoreScanThreads([], [job])[0];
      if (restored) dispatch({ type: 'thread/addBackground', thread: restored });
    }
    dispatch({ type: 'active/set', id: job.threadId });
  }, []);
  const deleteThread = useCallback((id: string) => {
    const related = stateRef.current.queueJobs.filter((job) => job.threadId === id);
    for (const job of related) {
      if (job.status !== 'queued' && job.status !== 'running') continue;
      cancelledQueueIds.current.add(job.id);
      if (runningQueueId.current === job.id) queueAbort.current?.abort();
    }
    dispatch({ type: 'thread/remove', id });
  }, []);
  const clearHistory = useCallback(() => {
    abort.current?.abort();
    for (const job of stateRef.current.queueJobs) {
      if (job.status !== 'queued' && job.status !== 'running') continue;
      cancelledQueueIds.current.add(job.id);
      if (runningQueueId.current === job.id) queueAbort.current?.abort();
    }
    queueAbort.current?.abort();
    dispatch({ type: 'threads/clear' });
  }, []);

  const activeThread = useMemo(
    () => state.threads.find((thread) => thread.id === state.activeId) ?? null,
    [state.threads, state.activeId],
  );

  const trialLeft =
    state.access.kind === 'trial' ? state.access.left : 0;

  const value = useMemo<Store>(
    () => ({
      ...state,
      activeThread,
      streaming: state.streamingId !== null,
      trialLeft,
      canAsk: state.access.kind === 'shared' || state.access.kind === 'own' || trialLeft > 0,
      newChat,
      openThread,
      openScanResult,
      send,
      stop,
      readShot,
      enqueueScan,
      cancelQueue,
      unlock,
      saveOwnKeys,
      forgetAccess,
      deleteThread,
      clearHistory,
      setThoroughness,
      setAnswerStyle,
      setAppLanguage,
    }),
    [
      state,
      activeThread,
      trialLeft,
      newChat,
      openThread,
      openScanResult,
      send,
      stop,
      readShot,
      enqueueScan,
      cancelQueue,
      unlock,
      saveOwnKeys,
      forgetAccess,
      deleteThread,
      clearHistory,
      setThoroughness,
      setAnswerStyle,
      setAppLanguage,
    ],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore(): Store {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useStore must be used inside StoreProvider');
  return ctx;
}
