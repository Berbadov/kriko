/**
 * The phone's small catalog of what the reader has already researched.
 *
 * The desktop keeps a knowledge store; the phone keeps only what fits in a
 * prompt: one row per product, the question that led to it, a short gist of the
 * answer and the pages it rested on. "The previous one" is resolved against
 * this list, so two products must stay two rows and never merge.
 *
 * Rows are derived, never saved separately: the conversation threads and the
 * scan queue are the record, and the catalog is a bounded view of them. A
 * deleted thread therefore forgets its product, which is what a reader expects.
 */

import type { QueueJob, Reading, Source, Thread } from './types';

/** One page a remembered answer rested on. */
export interface CatalogSource {
  title: string;
  host: string;
  url: string;
}

/** One product the reader researched on this phone. */
export interface CatalogEntry {
  /** Folded identity: what dedupe compares, so a rescan is still one product. */
  key: string;
  brand: string;
  product: string;
  model: string;
  /** One line a reader (and the model) can name the product by. */
  title: string;
  /** The last question asked about this product. */
  question: string;
  /** A short gist of the answer; empty when the turn failed. */
  gist: string;
  /** Up to four pages the answer rested on. */
  sources: CatalogSource[];
  /** The chat that can be reopened from History; absent for a lost scan. */
  threadId?: string;
  updatedAt: number;
  kind: 'scan' | 'chat';
}

/** Most rows a prompt brief is built from. */
export const MAX_CATALOG_ROWS = 8;
export const MAX_CATALOG_SOURCES = 4;
/** Hard ceiling for `memoryBrief`, so the catalog cannot crowd out the turn. */
export const MEMORY_BRIEF_LIMIT = 1600;

function flat(value: unknown, limit: number): string {
  return typeof value === 'string' ? value.replace(/\s+/g, ' ').trim().slice(0, limit) : '';
}

function finite(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : 0;
}

interface Identity {
  brand: string;
  product: string;
  model: string;
  title: string;
}

/**
 * What the reading saw. A provisional visual name is the product when no text
 * identified one: it is still a distinct product to keep apart.
 */
function identityOf(reading: Reading | null | undefined, fallbackName: string): Identity {
  const brand = flat(reading?.brand, 80);
  const product = flat(reading?.product, 160);
  const model = flat(reading?.model, 80);
  const visualName = flat(reading?.visualCandidates?.[0]?.name, 160);
  const described = flat(reading?.visualDescription, 160);
  const title = [brand, product, model].filter(Boolean).join(' ')
    || visualName
    || described
    || flat(fallbackName, 160);
  return { brand, product, model, title };
}

/** Case and spacing folded, never translated: two spellings of one product. */
function fold(value: string): string {
  return value.toLocaleLowerCase().replace(/\s+/g, ' ').trim();
}

function identityKey(identity: Identity, question: string): string {
  const named = [identity.brand, identity.product, identity.model].filter(Boolean).join('|');
  if (named) return fold(named);
  // Without identity fields the reader-facing name is the identity.
  return fold(identity.title || question);
}

function sourcesOf(sources: readonly Source[] | undefined): CatalogSource[] {
  const rows: CatalogSource[] = [];
  const seen = new Set<string>();
  for (const source of sources ?? []) {
    const url = flat(source.url, 300);
    if (!url || seen.has(url)) continue;
    seen.add(url);
    rows.push({ title: flat(source.title, 120), host: flat(source.host, 80), url });
    if (rows.length === MAX_CATALOG_SOURCES) break;
  }
  return rows;
}

interface RowInput {
  reading: Reading | null | undefined;
  fallbackName: string;
  question: string;
  answer: string;
  sources: readonly Source[] | undefined;
  threadId?: string;
  updatedAt: number;
  kind: CatalogEntry['kind'];
}

/** One row, or null when the turn had no product and no question in it. */
function rowOf(input: RowInput): CatalogEntry | null {
  const question = flat(input.question, 240);
  const identity = identityOf(input.reading, input.fallbackName);
  if (!identity.title && !question) return null;
  return {
    key: identityKey(identity, question),
    brand: identity.brand,
    product: identity.product,
    model: identity.model,
    title: identity.title,
    question,
    gist: flat(input.answer, 240),
    sources: sourcesOf(input.sources),
    threadId: input.threadId,
    updatedAt: finite(input.updatedAt) || Date.now(),
    kind: input.kind,
  };
}

/** The finished answer that belongs to the user message at `index`, if any. */
function answerAfter(thread: Thread, index: number): { text: string; sources?: Source[]; createdAt: number; pending: boolean; error?: string } | null {
  for (let next = index + 1; next < thread.messages.length; next += 1) {
    const message = thread.messages[next];
    if (message.role !== 'assistant') continue;
    return { text: message.text, sources: message.sources, createdAt: message.createdAt, pending: message.pending === true, error: message.error };
  }
  return null;
}

/** Rows from one conversation: one per product the reader shared an image of. */
function rowsFromThread(thread: Thread): CatalogEntry[] {
  const rows: CatalogEntry[] = [];
  let sharedProduct = false;
  for (let index = 0; index < thread.messages.length; index += 1) {
    const message = thread.messages[index];
    if (message.role !== 'user' || !message.reading) continue;
    sharedProduct = true;
    const answer = answerAfter(thread, index);
    // A turn still being written is not remembered yet; it never was finished.
    if (!answer || answer.pending) continue;
    const row = rowOf({
      reading: message.reading,
      fallbackName: thread.title,
      question: message.text,
      answer: answer.text,
      sources: answer.sources,
      threadId: thread.id,
      updatedAt: answer.createdAt || message.createdAt,
      kind: 'chat',
    });
    if (row) rows.push(row);
  }
  if (sharedProduct) return rows;

  // A conversation can name its product only in words ("a used D-18 drill").
  // Its title stands in for the identity, so a follow-up can still name it.
  const asked = thread.messages.find((message) => message.role === 'user' && message.text.trim());
  const answers = thread.messages.filter((message) => message.role === 'assistant' && !message.pending);
  const answer = answers[answers.length - 1];
  if (!asked || !answer) return rows;
  const row = rowOf({
    reading: null,
    fallbackName: thread.title,
    question: asked.text,
    answer: answer.text,
    sources: answer.sources,
    threadId: thread.id,
    updatedAt: Math.max(finite(thread.updatedAt), finite(answer.createdAt)),
    kind: 'chat',
  });
  if (row) rows.push(row);
  return rows;
}

/** A finished scan is one product; a queued or running one is not memory yet. */
function rowFromJob(job: QueueJob): CatalogEntry | null {
  if (job.status === 'queued' || job.status === 'running') return null;
  return rowOf({
    reading: job.reading,
    fallbackName: job.question,
    question: job.question,
    answer: job.text,
    sources: job.sources,
    threadId: job.threadId,
    updatedAt: Math.max(finite(job.updatedAt), finite(job.createdAt)),
    kind: 'scan',
  });
}

/**
 * The catalog: newest product first, one row per identity, capped small enough
 * to read in a prompt.
 */
export function buildCatalog(threads: readonly Thread[], jobs: readonly QueueJob[]): CatalogEntry[] {
  const rows: CatalogEntry[] = [];
  const scanThreads = new Set(jobs.flatMap((job) => job.threadId ? [job.threadId] : []));
  for (const job of jobs) {
    const row = rowFromJob(job);
    if (row) rows.push(row);
  }
  for (const thread of threads) {
    // A scan's thread is the same product as its job; the job is the record.
    if (scanThreads.has(thread.id)) continue;
    rows.push(...rowsFromThread(thread));
  }

  const newest = new Map<string, CatalogEntry>();
  for (const row of rows) {
    const known = newest.get(row.key);
    if (!known || row.updatedAt > known.updatedAt) newest.set(row.key, row);
  }
  return [...newest.values()]
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .slice(0, MAX_CATALOG_ROWS);
}

function clamp(value: string, limit: number): string {
  return value.length > limit ? `${value.slice(0, Math.max(0, limit - 1)).trimEnd()}…` : value;
}

/**
 * The catalog as prompt text, clearly the reader's own record rather than new
 * evidence, and bounded to `MEMORY_BRIEF_LIMIT` characters.
 */
export function memoryBrief(entries: readonly CatalogEntry[]): string {
  if (!entries.length) return '';
  const header = "The reader's own phone catalog: products researched in earlier conversations on this phone, newest first. Use it only to resolve which product a follow-up refers to; it is not new evidence, and two rows are always two different products.";
  const lines = [header];
  let used = header.length;
  for (const entry of entries) {
    const sources = entry.sources
      .slice(0, 3)
      .map((source) => source.host || source.title)
      .filter(Boolean)
      .join(', ');
    const parts = [
      `- ${entry.title || entry.question} [${entry.kind}]`,
      entry.question ? `asked: ${clamp(entry.question, 140)}` : '',
      entry.gist ? `answer: ${clamp(entry.gist, 160)}` : '',
      sources ? `sources: ${clamp(sources, 90)}` : '',
    ].filter(Boolean);
    const line = parts.join('; ');
    if (used + line.length + 1 > MEMORY_BRIEF_LIMIT) break;
    lines.push(line);
    used += line.length + 1;
  }
  return lines.join('\n');
}
