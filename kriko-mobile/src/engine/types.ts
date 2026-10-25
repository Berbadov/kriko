/**
 * The vocabulary of one Kriko Agent conversation.
 *
 * A thread is the message list the reader sees; a message is either their own
 * words (with the screenshot they shared) or one answer, with the searches it
 * ran and the pages it read kept beside it. Nothing here is derived from time:
 * the run engine reports real events, so a stopped turn says what it had when
 * it stopped instead of pretending to have finished.
 */

import { productReadingTitle } from './reading';

/** The two keys Kriko Agent spends. They live in the phone's secure storage. */
export interface ProviderKeys {
  mercury: string;
  deepseek: string;
}

export type AccessKind = 'none' | 'trial' | 'shared' | 'own';

/** What the app may say about the keys it holds — never a key itself. */
export interface AccessState {
  kind: AccessKind;
  /** "Release test", or the words the friend used when they pasted the code. */
  label: string;
  /** Trial questions left; 0 for an access code or the reader's own keys. */
  left: number;
  /** The trial's own ceiling, from the baked bundle. */
  limit: number;
}

export type StepKind = 'search' | 'fetch' | 'note' | 'error';

/** One line of work, as it happened. */
export interface Step {
  id: string;
  kind: StepKind;
  text: string;
  at: number;
}

/** A page the turn actually saw. `n` is what a citation like [2] points at. */
export interface Source {
  n: number;
  url: string;
  title: string;
  host: string;
}

export interface VisualCandidate {
  name: string;
  confidence: 'high' | 'medium' | 'low';
  /** Visible design features supporting this provisional match. */
  reason: string;
}

/** What the vision pass observed in a shared product photo or screenshot. */
export interface Reading {
  brand: string;
  product: string;
  model: string;
  price: string;
  condition: string;
  /** The listing's own words: title, specs, seller claims. */
  detail: string;
  /** One honest sentence about what the image did not settle. */
  note: string;
  /** Optional source information for a visible product/review page. */
  site?: string;
  url?: string;
  visualDescription?: string;
  identityBasis?: 'text' | 'appearance' | 'mixed' | 'unknown';
  /** Search leads from appearance, never confirmed model codes. */
  visualCandidates?: VisualCandidate[];
}

export type ResearchMode = 'research' | 'site_reviews';

export type Role = 'user' | 'assistant';

/** One named change the turn proposed in the app. The phone performs the ones
 *  its own screens have; a screen it does not have is named, never invented. */
export interface AppAction {
  id: string;
  kind: 'open' | string;
  status: 'proposed' | 'done' | 'failed' | string;
  title: string;
  detail: string;
  params?: Record<string, unknown>;
}

export interface Message {
  id: string;
  role: Role;
  text: string;
  createdAt: number;
  /** Steps the turn ran, kept so a finished answer still shows its work. */
  steps?: Step[];
  sources?: Source[];
  /** Changes the turn proposed, drawn under the answer. */
  actions?: AppAction[];
  /** The reading a screenshot turn was asked about. */
  reading?: Reading;
  /** The picked image, shown in the user's bubble. */
  imageUri?: string;
  /** True while the turn is still running. */
  pending?: boolean;
  stopped?: boolean;
  /** Why the turn failed, in words the reader can act on. */
  error?: string;
  /** The answer rested on titles or snippets, not readable page text. */
  unverified?: boolean;
}

export interface Thread {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messages: Message[];
}

export type QueueJobStatus = 'queued' | 'running' | 'done' | 'error' | 'cancelled';

/** One product captured by the floating scanner, researched outside the open chat. */
export interface QueueJob {
  id: string;
  question: string;
  researchMode?: ResearchMode;
  reviewSite?: string;
  reading: Reading;
  imageUri?: string;
  status: QueueJobStatus;
  text: string;
  sources: Source[];
  steps: Step[];
  error?: string;
  threadId?: string;
  answerId?: string;
  createdAt: number;
  updatedAt: number;
}

/** Remove the scan records that would otherwise rebuild explicitly deleted chats. */
export function withoutScanThreads(jobs: QueueJob[], threadIds: ReadonlySet<string>): QueueJob[] {
  return jobs.filter((job) => !job.threadId || !threadIds.has(job.threadId));
}

/** Rebuild the chat-side result from the durable scan record after a process death. */
export function restoreScanThreads(threads: Thread[], jobs: QueueJob[]): Thread[] {
  const restored = [...threads];
  const now = Date.now();
  const finiteTime = (value: number, fallback: number) =>
    Number.isFinite(value) && value > 0 ? value : fallback;

  for (const job of jobs) {
    if (!job.threadId) continue;
    const createdAt = finiteTime(job.createdAt, now);
    const updatedAt = Math.max(createdAt, finiteTime(job.updatedAt, createdAt));
    const threadIndex = restored.findIndex((thread) => thread.id === job.threadId);
    if (threadIndex < 0) {
      const title = productReadingTitle(job.reading, true).slice(0, 64) || 'Product scan';
      restored.unshift({
        id: job.threadId,
        title,
        createdAt,
        updatedAt,
        messages: [
          {
            id: `${job.id}-user`,
            role: 'user',
            text: job.question,
            createdAt,
            reading: job.reading,
            imageUri: job.imageUri,
          },
          {
            id: job.answerId || `${job.id}-answer`,
            role: 'assistant',
            text: job.text || '',
            createdAt: createdAt + 1,
            steps: job.steps ?? [],
            sources: job.sources ?? [],
            pending: job.status === 'queued' || job.status === 'running',
            error: job.status === 'error' ? job.error : undefined,
            stopped: job.status === 'cancelled',
          },
        ],
      });
      continue;
    }

    const thread = restored[threadIndex];
    const answerIndex = thread.messages.findIndex((message) => message.id === job.answerId);
    const fallbackAnswerIndex = answerIndex < 0
      ? [...thread.messages].map((message) => message.role).lastIndexOf('assistant')
      : answerIndex;
    if (fallbackAnswerIndex >= 0) {
      const messages = [...thread.messages];
      const answer = messages[fallbackAnswerIndex];
      messages[fallbackAnswerIndex] = {
        ...answer,
        text: job.text || answer.text,
        steps: job.steps?.length ? job.steps : answer.steps,
        sources: job.sources?.length ? job.sources : answer.sources,
        pending: job.status === 'queued' || job.status === 'running',
        error: job.status === 'error' ? job.error || answer.error : answer.error,
        stopped: job.status === 'cancelled' || answer.stopped,
      };
      restored[threadIndex] = {
        ...thread,
        updatedAt: Math.max(finiteTime(thread.updatedAt, createdAt), updatedAt),
        messages,
      };
    }
  }
  return restored.sort((a, b) => finiteTime(b.updatedAt, 0) - finiteTime(a.updatedAt, 0));
}

/** What a finished turn hands back to the store. */
export interface TurnResult {
  text: string;
  steps: Step[];
  sources: Source[];
  actions: AppAction[];
  searches: number;
  reads: number;
  unverified: boolean;
  stopped: boolean;
  error: string;
}
