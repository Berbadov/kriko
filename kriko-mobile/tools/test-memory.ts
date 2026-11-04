/**
 * The phone catalog: products must stay two rows, follow-ups must be able to
 * name them, and the prompt brief must never grow past its cap.
 */

import assert from 'node:assert/strict';

import { buildCatalog, memoryBrief, MEMORY_BRIEF_LIMIT, MAX_CATALOG_ROWS, MAX_CATALOG_SOURCES, type CatalogEntry } from '../src/engine/memory';
import { SYSTEM_PROMPT } from '../src/engine/prompt';
import { runTurn } from '../src/engine/providers';
import type { Message, QueueJob, Reading, Source, Thread } from '../src/engine/types';

function reading(brand: string, product: string, model: string, price = '', condition = 'used'): Reading {
  return { brand, product, model, price, condition, detail: '', note: '' };
}

const DRILL = reading('Acme', '18 V drill', 'D-18', '€99', 'used');
const LAPTOP = reading('Lenovo', 'ThinkPad T14', 'Gen 3', '$900', 'used');

function source(n: number, host: string, title: string): Source {
  return { n, url: `https://${host}/page-${n}`, title, host };
}

function conversationThread(id: string, title: string, shared: Reading | null, question: string, answer: string, at: number, sources: Source[] = [], pending = false): Thread {
  const user: Message = { id: `${id}-u`, role: 'user', text: question, createdAt: at, ...(shared ? { reading: shared } : {}) };
  const reply: Message = {
    id: `${id}-a`,
    role: 'assistant',
    text: answer,
    createdAt: at + 100,
    sources,
    ...(pending ? { pending: true } : {}),
  };
  return { id, title, createdAt: at, updatedAt: at + 100, messages: [user, reply] };
}

function scanJob(id: string, shared: Reading, question: string, answer: string, at: number, status: QueueJob['status'] = 'done', sources: Source[] = []): QueueJob {
  return {
    id,
    question,
    reading: shared,
    status,
    text: answer,
    sources,
    steps: [],
    createdAt: at,
    updatedAt: at + 50,
  };
}

/** Two products, two rows, and a brief that names both. */
function distinctProducts(): void {
  const threads = [
    conversationThread('t-drill', 'Used D-18 drill', DRILL, 'What goes wrong with this drill?', 'The chuck can wobble after heavy use.', 1_000, [source(1, 'forum.example.com', 'D-18 owners')]),
    conversationThread('t-laptop', 'ThinkPad T14 Gen 3', LAPTOP, 'Any known issues?', 'The T14 Gen 3 has known USB-C port failures.', 2_000, [source(1, 'reviews.example.com', 'T14 review'), source(2, 'forum.example.com', 'T14 thread')]),
  ];
  const catalog = buildCatalog(threads, []);
  assert.equal(catalog.length, 2, 'two products are two rows');
  const [newest, oldest] = catalog;
  assert.equal(newest.kind, 'chat');
  assert.equal(newest.threadId, 't-laptop', 'newest first');
  assert.match(newest.title, /Lenovo/);
  assert.match(newest.title, /ThinkPad T14/);
  assert.match(oldest.title, /Acme/);
  assert.match(oldest.title, /D-18/);
  assert.equal(oldest.question, 'What goes wrong with this drill?');
  assert.match(oldest.gist, /chuck/);
  assert.equal(oldest.sources.length, 1);
  assert.equal(oldest.sources[0].host, 'forum.example.com');
  assert.notEqual(newest.key, oldest.key, 'identities stay distinct');

  const brief = memoryBrief(catalog);
  assert.ok(brief.length <= MEMORY_BRIEF_LIMIT, 'brief stays inside its cap');
  assert.match(brief, /phone catalog/);
  assert.match(brief, /Acme 18 V drill D-18/);
  assert.match(brief, /Lenovo ThinkPad T14 Gen 3/);
}

/** A finished scan is remembered; its sources are capped. */
function scannedProducts(): void {
  const sources = [1, 2, 3, 4, 5, 6].map((n) => source(n, `shop${n}.example.com`, `Shop ${n}`));
  const threads = [conversationThread('t-scan', 'Possible: 18 V drill', null, 'What should I check?', 'Check the chuck.', 500)];
  // The scan owns its thread: the job is the record, the thread is not doubled.
  const job = { ...scanJob('j1', DRILL, 'What is known to go wrong?', 'Reports of chuck wobble.', 1_500, 'done', sources), threadId: 't-scan' };
  const catalog = buildCatalog([...threads], [job]);
  assert.equal(catalog.length, 1, 'a scan thread and its job are one product');
  assert.equal(catalog[0].kind, 'scan');
  assert.equal(catalog[0].threadId, 't-scan');
  assert.equal(catalog[0].sources.length, MAX_CATALOG_SOURCES);
  assert.equal(catalog[0].updatedAt, 1_550);
}

/** The same product researched twice is one row, the newer one. */
function dedupeNewest(): void {
  const threads = [
    conversationThread('t-old', 'D-18 drill', DRILL, 'Old question', 'Old answer', 3_000),
    conversationThread('t-new', 'D-18 drill again', DRILL, 'New question', 'New answer', 6_000),
  ];
  const catalog = buildCatalog(threads, []);
  assert.equal(catalog.length, 1, 'one identity is one row');
  assert.equal(catalog[0].question, 'New question');
  assert.equal(catalog[0].gist, 'New answer');
  assert.equal(catalog[0].threadId, 't-new');
  assert.equal(catalog[0].updatedAt, 6_100);

  // A rescan (same identity) also replaces the older chat row.
  const rescanned = buildCatalog(threads, [scanJob('j2', DRILL, 'Rescan question', 'Rescan answer', 9_000)]);
  assert.equal(rescanned.length, 1);
  assert.equal(rescanned[0].kind, 'scan');
  assert.equal(rescanned[0].question, 'Rescan question');
}

/** A turn still being written is not memory yet. */
function pendingSkipped(): void {
  assert.equal(buildCatalog([conversationThread('t-pending', 'D-18', DRILL, 'Asked', 'Not finished', 1_000, [], true)], []).length, 0);
  assert.equal(buildCatalog([], [scanJob('j-queued', DRILL, 'Asked', '', 1_000, 'queued')]).length, 0);
  assert.equal(buildCatalog([], [scanJob('j-running', DRILL, 'Asked', '', 1_000, 'running')]).length, 0);
  assert.equal(buildCatalog([conversationThread('t-empty', '', null, '', '', 1_000)], []).length, 0, 'empty turns add no row');
  assert.equal(buildCatalog([], []).length, 0);
  assert.equal(memoryBrief([]), '');
}

/** A conversation that only named its product in words still gets a row. */
function fallbackIdentity(): void {
  const catalog = buildCatalog([conversationThread('t-words', 'A used D-18 drill', null, 'Is the D-18 reliable?', 'Mostly, with the caveat of chuck wobble.', 1_000)], []);
  assert.equal(catalog.length, 1);
  assert.equal(catalog[0].title, 'A used D-18 drill');
  assert.equal(catalog[0].brand, '');
  assert.equal(catalog[0].product, '');
}

/** The catalog is capped, newest first, and the brief truncates rather than grows. */
function bounded(): void {
  const jobs = Array.from({ length: 12 }, (_, index) => scanJob(
    `j-${index}`,
    reading(`Brand${index}`, `Product ${index}`, `M${index}`),
    `Question ${index} `.repeat(20),
    `Answer ${index} `.repeat(20),
    1_000 + index,
  ));
  const catalog = buildCatalog([], jobs);
  assert.equal(catalog.length, MAX_CATALOG_ROWS);
  assert.equal(catalog[0].title, 'Brand11 Product 11 M11', 'newest first');
  for (const entry of catalog) assert.ok(entry.sources.length <= MAX_CATALOG_SOURCES);

  const brief = memoryBrief(catalog);
  assert.ok(brief.length <= MEMORY_BRIEF_LIMIT, `brief is ${brief.length} chars`);
  assert.ok(brief.length > 0);
}

/** The turn carries the catalog, and prior readings keep their identity. */
async function turnWiring(): Promise<void> {
  const threads = [
    conversationThread('t-drill', 'D-18 drill', DRILL, 'What goes wrong with this drill?', 'Chuck wobble is reported.', 1_000, [source(1, 'forum.example.com', 'D-18 owners')]),
    conversationThread('t-laptop', 'ThinkPad T14', LAPTOP, 'Any known issues?', 'USB-C port failures are reported.', 2_000),
  ];
  const memory = buildCatalog(threads, []);
  const history = threads.flatMap((thread) => thread.messages);
  let seen: Record<string, unknown>[] = [];
  const result = await runTurn({
    keys: { mercury: 'test', deepseek: 'test' },
    history,
    question: 'And the previous one?',
    language: 'en',
    memory,
  }, {
    complete: async (input) => {
      seen = input.messages;
      return { text: 'The previous product is the Acme 18 V drill (D-18).', finish: 'stop', toolCalls: [] };
    },
    search: async () => ({ error: '', hits: [] }),
    fetch: async () => ({ title: '', pageText: '', error: '' }),
  });
  assert.equal(result.error, '');
  const system = String(seen[0]?.content ?? '');
  assert.match(system, /phone catalog/, 'the catalog is labelled in the system prompt');
  assert.match(system, /Acme 18 V drill D-18/);
  assert.match(system, /Lenovo ThinkPad T14/);

  const contents = seen.map((message) => String(message.content));
  assert.ok(contents.some((content) => /Brand: Acme/.test(content) && /Model: D-18/.test(content) && /Condition: used/.test(content)), 'a prior reading keeps brand, model and condition');
  assert.ok(contents.some((content) => /Brand: Lenovo/.test(content) && /Model: Gen 3/.test(content)), 'the second product keeps its own identity');
  assert.ok(contents.some((content) => /\[1\] D-18 owners — https:\/\/forum\.example\.com/.test(content)), 'the answer sources stay beside the answer');
}

/** The history budget is unchanged: readings ride inside it, not on top. */
async function historyBudget(): Promise<void> {
  const history: Message[] = Array.from({ length: 12 }, (_, index) => ({
    id: `m-${index}`,
    role: 'user' as const,
    text: `question ${index} ${'x'.repeat(3_000)}`,
    createdAt: index,
    reading: reading(`Brand${index}`, `Product ${index}`, `Model${index}`),
  }));
  let seen: Record<string, unknown>[] = [];
  await runTurn({
    keys: { mercury: 'test', deepseek: 'test' },
    history,
    question: 'Which of them?',
    language: 'en',
  }, {
    complete: async (input) => {
      seen = input.messages;
      return { text: 'Answer.', finish: 'stop', toolCalls: [] };
    },
    search: async () => ({ error: '', hits: [] }),
    fetch: async () => ({ title: '', pageText: '', error: '' }),
  });
  const past = seen.slice(1, -1);
  const total = past.reduce((sum, message) => sum + String(message.content).length, 0);
  assert.ok(total <= 14_000, `past turns use ${total} characters`);
  assert.ok(past.length > 0);
}

function promptRule(): void {
  assert.match(SYSTEM_PROMPT, /Never merge evidence between two different products/);
  assert.match(SYSTEM_PROMPT, /the previous one/);
  assert.match(SYSTEM_PROMPT, /name the product/i);
}

async function main() {
  distinctProducts();
  scannedProducts();
  dedupeNewest();
  pendingSkipped();
  fallbackIdentity();
  bounded();
  promptRule();
  await turnWiring();
  await historyBudget();
  console.log('Phone catalog memory checks passed.');
}

void main();
