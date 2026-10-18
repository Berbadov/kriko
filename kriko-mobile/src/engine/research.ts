/**
 * The run engine.
 *
 * A run is a pure function of time: `plan(query)` builds the work, and
 * `advance(plan, elapsedMs)` reports what is true at that moment. Nothing here
 * schedules timers, so pausing, stopping and reopening a thread from history all
 * come out consistent.
 *
 * The sources and claims below are fixtures — this build has no network. The
 * shapes match what a real search-then-read pass produces so the screens can be
 * wired to a live engine without changing the UI.
 */

import type { Claim, RunStep, Source, StepState } from './types';

export interface RunPlan {
  steps: RunStep[];
  sources: Source[];
  claims: Claim[];
  summary: string;
  written: number;
  totalMs: number;
  /** Simulated page count for the reading step. */
  pages: number;
  /** Sources that arrive while reading, and when. */
  arrivals: { at: number; source: Source }[];
  /** Progress milestones: search ends, reading ends, the file is written. */
  searchDone: number;
  readStart: number;
  readEnd: number;
  writeDone: number;
}

export interface RunView {
  steps: RunStep[];
  progress: number;
  progressLabel: string;
  sources: Source[];
  status: 'searching' | 'done';
  claims: Claim[];
  summary: string;
  written: number;
}

const BUDS: Omit<RunPlan, 'totalMs' | 'searchDone' | 'readStart' | 'readEnd' | 'writeDone'> = {
  pages: 4,
  written: 12,
  summary:
    'Sources agree on 6 h with noise cancelling on. The figure changes with volume, so the claim keeps its test condition.',
  sources: [{ n: 1, label: 'Web search', kind: 'search' }],
  arrivals: [
    { at: 1500, source: { n: 2, label: 'review-site.test', kind: 'page' } },
    { at: 2700, source: { n: 3, label: 'forum.test', kind: 'page' } },
    { at: 3900, source: { n: 4, label: 'shop.test', kind: 'page' } },
  ],
  claims: [
    {
      id: 'battery',
      title: 'Battery life',
      status: 'backed',
      body: '6 h with noise cancelling on. Four sources agree.',
    },
    {
      id: 'condition',
      title: 'Test condition',
      status: 'disputed',
      body: 'One source gives 6 h at full volume. Two give 8 h at moderate volume.',
    },
    {
      id: 'case',
      title: 'Charging case',
      status: 'backed',
      body: 'Wireless charging is listed by two sources.',
    },
  ],
  steps: [],
};

/** The claims a generic run reports, keyed off the words in the question. */
function genericClaims(query: string, web: boolean): Claim[] {
  const subject = query.trim() || 'this product';
  const claims: Claim[] = [
    {
      id: 'reported',
      title: 'What sources report',
      status: 'backed',
      body: web
        ? `Three sources describe ${subject}. Two of them agree on the headline figure.`
        : `The installed catalog covers ${subject} with two entries.`,
    },
    {
      id: 'gap',
      title: 'Left open',
      status: 'disputed',
      body: 'No source states a test condition, so the figures cannot be compared directly.',
    },
  ];
  return claims;
}

/**
 * Build the work for a question. The Galaxy Buds2 Pro fixture mirrors the
 * reference design; anything else falls back to a generic shape.
 */
export function plan(query: string, slug: string, web = true): RunPlan {
  const buds = slug === 'samsung-galaxy-buds2-pro';
  const pages = buds ? 4 : 3;
  const source = buds
    ? BUDS
    : {
        ...BUDS,
        pages,
        written: 7,
        summary: web
          ? 'The pages agree on the headline figure and disagree on the conditions behind it. The product file keeps both.'
          : 'The catalog answered without the web. Nothing was sent anywhere to build this file.',
        sources: web
          ? [{ n: 1, label: 'Web search', kind: 'search' as const }]
          : [{ n: 1, label: 'Installed catalog', kind: 'catalog' as const }],
        arrivals: web
          ? [
              { at: 1500, source: { n: 2, label: 'review-site.test', kind: 'page' as const } },
              { at: 2700, source: { n: 3, label: 'forum.test', kind: 'page' as const } },
            ]
          : [{ at: 1500, source: { n: 2, label: 'catalog.test', kind: 'catalog' as const } }],
        claims: genericClaims(query, web),
      };

  const searchDone = 1300;
  const readStart = searchDone;
  const perPage = buds ? 900 : 800;
  const readEnd = readStart + pages * perPage;
  const writeDone = readEnd + 1100;

  return {
    ...source,
    pages,
    searchDone,
    readStart,
    readEnd,
    writeDone,
    totalMs: writeDone,
  };
}

function stateOf(at: number, start: number, end: number): StepState {
  if (at >= end) return 'done';
  if (at >= start) return 'live';
  return 'queued';
}

/** What the run looks like `elapsedMs` after it started. */
export function advance(plan: RunPlan, elapsedMs: number): RunView {
  const t = Math.max(0, elapsedMs);
  const searching = t < plan.searchDone;
  const reading = t >= plan.readStart && t < plan.readEnd;
  const writing = t >= plan.readEnd && t < plan.writeDone;
  const done = t >= plan.writeDone;

  const pagesRead =
    done || writing
      ? plan.pages
      : Math.max(
          0,
          Math.min(
            plan.pages,
            Math.floor(((t - plan.readStart) / (plan.readEnd - plan.readStart)) * plan.pages),
          ),
        );
  const searchWord = plan.sources[0].kind === 'catalog' ? 'Read the catalog' : 'Searched the web';

  const steps: RunStep[] = [
    {
      id: 'search',
      title: searchWord,
      meta:
        plan.sources[0].kind === 'catalog'
          ? 'lookup · installed catalog'
          : 'search · ' + (plan.sources.length ? plan.sources[0].label.toLowerCase() : 'web'),
      state: stateOf(t, 0, plan.searchDone),
    },
    {
      id: 'read',
      title: 'Reading pages',
      meta: `read · ${pagesRead} of ${plan.pages} pages`,
      state: stateOf(t, plan.readStart, plan.readEnd),
    },
    {
      id: 'write',
      title: 'Writing the product file',
      meta: 'write · product.sqlite',
      state: stateOf(t, plan.readEnd, plan.writeDone),
    },
  ];

  const sources = plan.sources
    .concat(plan.arrivals.filter((a) => t >= a.at).map((a) => a.source))
    .sort((a, b) => a.n - b.n);

  let progress: number;
  let progressLabel: string;
  if (searching) {
    progress = Math.round((t / plan.searchDone) * 14);
    progressLabel = plan.sources[0].kind === 'catalog' ? 'reading the catalog' : 'searching the web';
  } else if (reading) {
    const f = (t - plan.readStart) / (plan.readEnd - plan.readStart);
    progress = Math.round(14 + f * 62);
    progressLabel = 'reading review pages';
  } else if (writing) {
    const f = (t - plan.readEnd) / (plan.writeDone - plan.readEnd);
    progress = Math.round(76 + f * 24);
    progressLabel = 'writing the product file';
  } else {
    progress = 100;
    progressLabel = 'done';
  }

  return {
    steps,
    progress,
    progressLabel,
    sources,
    status: done ? 'done' : 'searching',
    claims: done ? plan.claims : [],
    summary: done ? plan.summary : '',
    written: done ? plan.written : 0,
  };
}

/** The catalogue of what can be identified from a shared screenshot. */
export const SCREENSHOT_READING = {
  brand: 'Samsung',
  product: 'Galaxy Buds2 Pro',
  model: null,
  note: 'Not visible in the image',
};

export function slugify(value: string): string {
  return (
    value
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '')
      .slice(0, 48) || 'product'
  );
}
