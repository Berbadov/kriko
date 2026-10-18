/** Domain types shared by the reader, the run engine and the screens. */

export type ReaderStatus = 'absent' | 'downloading' | 'paused' | 'ready';

export interface ReaderState {
  status: ReaderStatus;
  /** 0..1, derived from `startedAt` while downloading. */
  progress: number;
  /** Pause the download on mobile data. */
  wifiOnly: boolean;
  modelId: string;
  modelSize: string;
  /** Epoch milliseconds when the download began. */
  startedAt?: number;
}

export type SourceKind = 'search' | 'page' | 'catalog';

export interface Source {
  n: number;
  label: string;
  kind: SourceKind;
}

export type StepState = 'queued' | 'live' | 'done';

export interface RunStep {
  id: 'search' | 'read' | 'write';
  title: string;
  /** The mono line under the title, e.g. "read · 2 of 4 pages". */
  meta: string;
  state: StepState;
}

export type ClaimStatus = 'backed' | 'disputed';

export interface Claim {
  id: string;
  title: string;
  status: ClaimStatus;
  body: string;
}

export type ThreadStatus = 'searching' | 'done' | 'stopped';

/**
 * A stored run. Only the seed is kept: the steps, sources and progress are
 * derived from `elapsedMs` (and the plan built from `query`), so reopening a
 * thread from history shows exactly what the run had reached.
 */
export interface Thread {
  id: string;
  /** Display name: "Samsung Galaxy Buds2 Pro". */
  title: string;
  /** "samsung-galaxy-buds2-pro". */
  slug: string;
  /** "samsung-galaxy-buds2-pro.sqlite". */
  file: string;
  /** The words the user asked with. */
  query: string;
  kind: 'text' | 'screenshot';
  web: boolean;
  startedAt: number;
  /** Milliseconds of work performed, frozen when the run is stopped. */
  elapsedMs: number;
  status: ThreadStatus;
  /**
   * The shared image: a file URI from the picker, or the bundled sample asset
   * module, which is why this is not typed as a plain string.
   */
  imageUri?: string | number;
}

/** A thread plus what the run had reached. */
export interface ThreadView extends Thread {
  steps: RunStep[];
  progress: number;
  progressLabel: string;
  sources: Source[];
  claims: Claim[];
  summary: string;
  written: number;
}

/** What the reader pulled out of a screenshot. */
export interface Identification {
  brand: string;
  product: string;
  model: string | null;
  /** Honest note about what the image did and did not show. */
  note: string;
}
