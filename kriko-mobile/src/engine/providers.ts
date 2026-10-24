/**
 * The two providers Kriko Agent is pinned to, and the turn that joins them.
 *
 * Mercury 3 is the researcher: OpenAI-compatible chat completions with tool
 * calls. DeepSeek Search and Fetch are the only tools it is given. The loop is
 * the desktop stack's, cut down for a phone: four model rounds, five retrieval
 * calls, a 120-second deadline, and every bound ends the turn with a sentence
 * instead of silence.
 *
 * There is no server in this path. The keys come from the phone's secure
 * storage, the provider calls leave the phone directly, and nothing is kept
 * anywhere but the conversation the reader can see.
 */

import { agentPrompt, siteReviewsPrompt, type AnswerStyle, VISION_PROMPT, turnBrief } from './prompt';
import { isReviewSiteUrl, normalizeReviewSite, resolveReviewSite, resolveReviewUrl, scopeReviewQuery, visibleReviewUrl } from './reviews';
import type {
  AppAction,
  Message,
  ProviderKeys,
  Reading,
  Source,
  StepKind,
  TurnResult,
} from './types';

export const MERCURY_URL = 'https://api.inceptionlabs.ai/v1/chat/completions';
export const DEEPSEEK_URL = 'https://api.deepseek.com';
export const AGENT_MODEL = 'mercury-3';
export const VISION_MODEL = 'deepseek-flash';

/** The desktop's default dial: five retrievals, four results each. */
export const MAX_TOOL_CALLS = 8;
export const MAX_RESULTS = 5;
export const MAX_TOOL_ROUNDS = 4;
export const TURN_SECONDS = 120;
const MERCURY_TIMEOUT = 45_000;
const RETRIEVAL_TIMEOUT = 10_000;
// Keep a real model call available to turn whatever evidence we collected
// into an answer. Retrieval must not spend the entire turn's wall clock.
// Includes one retrieval timeout after the last search, leaving the model's
// full provider timeout available for its final answer.
const SYNTHESIS_RESERVE_MS = MERCURY_TIMEOUT + RETRIEVAL_TIMEOUT;
const MIN_RESEARCH_WINDOW_MS = 8_000;
const MIN_EVIDENCE_CHARS = 200;
const PACING_MS = 220;

/** A request the reader can act on, with the provider's status kept for routing. */
export class ProviderError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ProviderError';
    this.status = status;
  }
}

export class RequestAborted extends Error {
  constructor() {
    super('stopped');
    this.name = 'RequestAborted';
  }
}

/* ------------------------------------------------------------- transport -- */

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

let lastCall = 0;

/** DeepSeek allows a handful of calls a second for the whole account. */
async function pace(): Promise<void> {
  const wait = lastCall + PACING_MS - Date.now();
  if (wait > 0) await sleep(wait);
  lastCall = Date.now();
}

function bodyOf(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' ? (value as Record<string, unknown>) : null;
}

function textOf(value: unknown): string {
  return typeof value === 'string' ? value : '';
}

function numberField(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

async function readError(response: Response): Promise<ProviderError> {
  let message = response.statusText || 'the provider refused the request';
  try {
    const text = await response.text();
    const parsed = bodyOf(JSON.parse(text));
    const error = bodyOf(parsed?.error);
    const detail = textOf(error?.message) || textOf(parsed?.message);
    if (detail) message = detail;
    else if (text && text.length < 400) message = text;
  } catch {
    // The status is the honest part when the body is not JSON.
  }
  return new ProviderError(response.status, message.slice(0, 300));
}

/** `fetch` with a provider timeout, cancelled by the turn's own signal. */
async function postJson(
  url: string,
  apiKey: string,
  body: unknown,
  signal: AbortSignal | undefined,
  timeoutMs: number,
): Promise<Record<string, unknown>> {
  if (signal?.aborted) throw new RequestAborted();
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const onAbort = () => controller.abort();
  signal?.addEventListener('abort', onAbort);

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!response.ok) throw await readError(response);
    const parsed = bodyOf(await response.json());
    if (!parsed) throw new ProviderError(0, 'the provider answered with an unreadable body');
    return parsed;
  } catch (error) {
    if (error instanceof ProviderError) throw error;
    if (error instanceof RequestAborted) throw error;
    if (timedOut) throw new ProviderError(0, 'did not answer in time');
    if (signal?.aborted) throw new RequestAborted();
    throw new ProviderError(0, 'could not be reached');
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', onAbort);
  }
}

/* ----------------------------------------------------------------- mercury -- */

export interface ToolCall {
  id: string;
  name: string;
  arguments: string;
}

export interface Completion {
  text: string;
  toolCalls: ToolCall[];
  finish: string;
}

interface MercuryDelta {
  content?: unknown;
  tool_calls?: unknown;
}

interface StreamHandlers {
  onData: (data: Record<string, unknown>) => void;
  signal?: AbortSignal;
  timeoutMs: number;
}

/** A chat-completions SSE stream, read through XHR because Hermes has no ReadableStream. */
function streamMercury(url: string, apiKey: string, payload: unknown, handlers: StreamHandlers): Promise<void> {
  return new Promise((resolve, reject) => {
    if (handlers.signal?.aborted) {
      reject(new RequestAborted());
      return;
    }
    const xhr = new XMLHttpRequest();
    let seen = 0;
    let tail = '';
    let settled = false;
    let timedOut = false;

    const settle = (error?: Error) => {
      if (settled) return;
      settled = true;
      handlers.signal?.removeEventListener('abort', onAbort);
      if (error) reject(error);
      else resolve();
    };

    const onAbort = () => {
      xhr.abort();
      settle(new RequestAborted());
    };
    handlers.signal?.addEventListener('abort', onAbort);

    const consume = (final: boolean) => {
      const text = xhr.responseText || '';
      if (text.length < seen) seen = 0; // defensive: a restarted body
      tail += text.slice(seen);
      seen = text.length;
      let newline = tail.indexOf('\n');
      while (newline !== -1) {
        const line = tail.slice(0, newline).replace(/\r$/, '');
        tail = tail.slice(newline + 1);
        if (line.startsWith('data:')) {
          const raw = line.slice(5).trim();
          if (raw === '[DONE]') {
            // The server still closes the socket; nothing more to read.
          } else if (raw) {
            try {
              const data = bodyOf(JSON.parse(raw));
              if (data) handlers.onData(data);
            } catch (error) {
              // A keepalive or a split frame is ignored; a handler that threw
              // is a real failure and must end the stream.
              if (error instanceof Error && error.name !== 'SyntaxError') settle(error);
            }
          }
        }
        newline = tail.indexOf('\n');
      }
      if (final && tail.trim().startsWith('data:')) {
        const raw = tail.trim().slice(5).trim();
        tail = '';
        if (raw && raw !== '[DONE]') {
          try {
            const data = bodyOf(JSON.parse(raw));
            if (data) handlers.onData(data);
          } catch {
            // An incomplete final frame is not an answer.
          }
        }
      }
    };

    xhr.open('POST', url);
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.setRequestHeader('Accept', 'text/event-stream');
    xhr.setRequestHeader('Authorization', `Bearer ${apiKey}`);
    xhr.timeout = handlers.timeoutMs;
    xhr.onreadystatechange = () => {
      if (xhr.readyState === 3) consume(false);
      if (xhr.readyState === 4) {
        consume(true);
        if (xhr.status >= 400) {
          let message = xhr.statusText || 'the provider refused the request';
          try {
            const parsed = bodyOf(JSON.parse(xhr.responseText || '{}'));
            const error = bodyOf(parsed?.error);
            message = textOf(error?.message) || textOf(parsed?.message) || message;
          } catch {
            // Keep the status text.
          }
          settle(new ProviderError(xhr.status, message.slice(0, 300)));
        } else {
          settle();
        }
      }
    };
    // React Native's XHR fires progress for each chunk while readyState stays
    // 3, so this is where a streamed answer actually arrives.
    xhr.onprogress = () => {
      if (xhr.readyState >= 3) consume(false);
    };
    xhr.onerror = () => settle(new ProviderError(0, 'could not be reached'));
    xhr.ontimeout = () => {
      timedOut = true;
      settle(new ProviderError(0, 'did not answer in time'));
    };
    xhr.onabort = () => {
      if (!timedOut) settle(new RequestAborted());
    };
    xhr.send(JSON.stringify(payload));
  });
}

const TURN_TOOLS: { type: string; function: Record<string, unknown> }[] = [
  {
    type: 'function',
    function: {
      name: 'search',
      description:
        'Search the web. Returns source URLs, snippets and page text, each row carrying the number to cite. Decide the kind of source first and put that kind’s own word in the query.',
      parameters: {
        type: 'object',
        properties: {
          query: { type: 'string', minLength: 1, maxLength: 128 },
          count: { type: 'integer', minimum: 1, maximum: MAX_RESULTS },
          kind: {
            type: 'string',
            enum: ['forums', 'reviews', 'recalls', 'manufacturer', 'video', 'news'],
            description: 'The kind of source this search is for.',
          },
        },
        required: ['query'],
        additionalProperties: false,
      },
    },
  },
  {
    type: 'function',
    function: {
      name: 'fetch',
      description:
        'Read a result URL returned by search when the result has no usable page text. In site review mode, the exact product URL supplied by the reader may also be read.',
      parameters: {
        type: 'object',
        properties: { url: { type: 'string', maxLength: 2048 } },
        required: ['url'],
        additionalProperties: false,
      },
    },
  },
];

const KIND_WORDS = new Set(['forums', 'reviews', 'recalls', 'manufacturer', 'video', 'news']);

/** The screens this phone actually has, in the app's own names. */
export const MOBILE_SCREENS: Record<string, string> = {
  chat: 'Chat',
  settings: 'Settings',
  history: 'History',
  about: 'About',
};

TURN_TOOLS.push({
  type: 'function',
  function: {
    name: 'open',
    description:
      'Offer to take the reader to a screen in Kriko when they asked to see it ("show me my history", "open settings"). The phone draws an Open button; say it is ready rather than that it already happened. Never use it to end an answer.',
    parameters: {
      type: 'object',
      properties: {
        screen: { type: 'string', enum: Object.keys(MOBILE_SCREENS) },
      },
      required: ['screen'],
      additionalProperties: false,
    },
  },
});

function clipQuery(query: string): string {
  const flat = query.replace(/\s+/g, ' ').trim();
  if (flat.length <= 128) return flat;
  const cut = flat.slice(0, 128);
  const space = cut.lastIndexOf(' ');
  return (space > 64 ? cut.slice(0, space) : cut).trim();
}

export interface MercuryRequest {
  apiKey: string;
  messages: Record<string, unknown>[];
  tools: unknown[];
  requireTools: boolean;
  signal?: AbortSignal;
  timeoutMs: number;
  onText?: (delta: string) => void;
  onDiscardText?: () => void;
}

function textToolCalls(text: string): ToolCall[] {
  const calls: ToolCall[] = [];
  const block = /<\|tool_call_start\|>([\s\S]*?)(?:<\|tool_call_end\|>|$)/g;
  let match: RegExpExecArray | null;
  while ((match = block.exec(text)) !== null) {
    const body = match[1];
    const fn = body.match(/<\s*function\s*=\s*([A-Za-z_][\w-]*)\s*>/);
    if (!fn) continue;
    const args: Record<string, string> = {};
    const parameter = /<\s*parameter\s*=\s*([A-Za-z_][\w-]*)\s*>([\s\S]*?)<\s*\/\s*parameter\s*>/g;
    let next: RegExpExecArray | null;
    while ((next = parameter.exec(body)) !== null) {
      args[next[1]] = next[2].trim();
    }
    calls.push({
      id: `raw-${calls.length}-${Date.now().toString(36)}`,
      name: fn[1],
      arguments: JSON.stringify(args),
    });
  }
  return calls;
}

async function callMercury(request: MercuryRequest): Promise<Completion> {
  const toolCalls = new Map<number, ToolCall>();
  let finish = '';
  let streamText = '';
  let buffer = '';
  let flushTimer: ReturnType<typeof setTimeout> | null = null;
  let sawToolCall = false;

  const flush = () => {
    if (flushTimer) {
      clearTimeout(flushTimer);
      flushTimer = null;
    }
    if (!buffer) return;
    const chunk = buffer;
    buffer = '';
    request.onText?.(chunk);
  };
  const pushText = (delta: string) => {
    streamText += delta;
    if (sawToolCall) return;
    buffer += delta;
    if (!flushTimer) {
      flushTimer = setTimeout(flush, 40);
    }
  };

  const payload: Record<string, unknown> = {
    model: AGENT_MODEL,
    messages: request.messages,
    stream: true,
    stream_options: { include_usage: true },
    temperature: 0.5,
    max_tokens: 2048,
    reasoning_effort: 'low',
  };
  if (request.tools.length) {
    payload.tools = request.tools;
    payload.tool_choice = request.requireTools ? 'required' : 'auto';
  }

  try {
    await streamMercury(MERCURY_URL, request.apiKey, payload, {
      signal: request.signal,
      timeoutMs: request.timeoutMs,
      onData: (data) => {
        if (data.error) throw new ProviderError(0, 'the model returned a stream error');
        for (const rawChoice of Array.isArray(data.choices) ? data.choices : []) {
          const choice = bodyOf(rawChoice);
          if (!choice) continue;
          const reason = textOf(choice.finish_reason);
          if (reason) finish = reason;
          const delta = bodyOf(choice.delta) as MercuryDelta | null;
          if (!delta) continue;
          const content = delta.content;
          if (typeof content === 'string') pushText(content);
          else if (Array.isArray(content)) {
            for (const part of content) {
              const piece = bodyOf(part);
              if (textOf(piece?.type) === 'text') pushText(textOf(piece?.text));
            }
          }
          for (const rawCall of Array.isArray(delta.tool_calls) ? delta.tool_calls : []) {
            const part = bodyOf(rawCall);
            if (!part) continue;
            if (!sawToolCall) {
              sawToolCall = true;
              buffer = '';
              request.onDiscardText?.();
            }
            const index = numberField(part.index);
            if (index === undefined) continue;
            const call = toolCalls.get(index) ?? { id: '', name: '', arguments: '' };
            const id = textOf(part.id);
            if (id) call.id = id;
            const fn = bodyOf(part.function);
            const name = textOf(fn?.name);
            const args = textOf(fn?.arguments);
            if (name) call.name += name;
            if (args) call.arguments += args;
            toolCalls.set(index, call);
          }
        }
      },
    });
  } finally {
    flush();
  }

  if (finish === 'length') {
    throw new ProviderError(0, 'the model hit its response limit before finishing');
  }
  if (finish !== 'stop' && finish !== 'tool_calls' && finish !== '') {
    throw new ProviderError(0, 'the model stream ended before a complete answer');
  }

  // Mercury normally returns tool calls in the structured field. Occasionally
  // it writes its own call syntax into the text instead; executing that text is
  // the difference between an answer and a screen full of <|tool_call_start|>.
  let text = streamText;
  if (toolCalls.size === 0 && text.includes('<|tool_call_start|>')) {
    const parsed = textToolCalls(text);
    if (parsed.length) {
      parsed.forEach((call, index) => toolCalls.set(index, call));
      request.onDiscardText?.();
    }
  }
  text = text
    .replace(/<\|tool_call_start\|>[\s\S]*?(?:<\|tool_call_end\|>|$)/g, '')
    .replace(/<\|[^|]+\|>/g, '')
    .trim();

  return {
    text,
    toolCalls: [...toolCalls.entries()].sort((a, b) => a[0] - b[0]).map(([, call]) => call),
    finish,
  };
}

/* ------------------------------------------------------------ deepseek -- */

export interface SearchHit {
  url: string;
  title: string;
  snippet: string;
  pageText: string;
}

function httpsUrl(value: unknown): string {
  const raw = textOf(value).trim();
  if (!/^https?:\/\//i.test(raw)) return '';
  try {
    const url = new URL(raw);
    if (!url.hostname) return '';
    url.hash = '';
    return url.toString().slice(0, 2048);
  } catch {
    return '';
  }
}

function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

export interface SearchOutcome {
  hits: SearchHit[];
  error: string;
}

export async function searchWeb(
  query: string,
  count: number,
  apiKey: string,
  signal?: AbortSignal,
  timeoutMs = RETRIEVAL_TIMEOUT,
): Promise<SearchOutcome> {
  const text = clipQuery(query);
  if (!text) return { hits: [], error: 'The search had no words in it.' };
  await pace();
  try {
    const data = await postJson(
      `${DEEPSEEK_URL}/v1/tools/search`,
      apiKey,
      { query: text, count: Math.max(1, Math.min(count, MAX_RESULTS)), need_content: true },
      signal,
      timeoutMs,
    );
    const rows = Array.isArray(data.results) ? data.results : [];
    const hits: SearchHit[] = [];
    for (const raw of rows) {
      const row = bodyOf(raw);
      if (!row) continue;
      const url = httpsUrl(row.url);
      if (!url) continue;
      hits.push({
        url,
        title: textOf(row.title).slice(0, 500),
        snippet: (textOf(row.snippet) || textOf(row.summary)).slice(0, 600),
        pageText: textOf(row.content).slice(0, 4000),
      });
      if (hits.length >= MAX_RESULTS) break;
    }
    return { hits, error: '' };
  } catch (error) {
    if (error instanceof RequestAborted) throw error;
    if (error instanceof ProviderError) return { hits: [], error: error.message };
    return { hits: [], error: 'the search service could not be reached' };
  }
}

export interface FetchOutcome {
  title: string;
  pageText: string;
  error: string;
}

export async function fetchPage(
  url: string,
  apiKey: string,
  signal?: AbortSignal,
  timeoutMs = RETRIEVAL_TIMEOUT,
): Promise<FetchOutcome> {
  const clean = httpsUrl(url);
  if (!clean) return { title: '', pageText: '', error: 'That is not a readable page address.' };
  await pace();
  try {
    const data = await postJson(
      `${DEEPSEEK_URL}/v1/tools/fetch`,
      apiKey,
      { url: clean },
      signal,
      timeoutMs,
    );
    const pageText = textOf(data.content).slice(0, 4000);
    if (!pageText) return { title: '', pageText: '', error: 'the page returned no readable text' };
    return { title: textOf(data.title).slice(0, 500), pageText, error: '' };
  } catch (error) {
    if (error instanceof RequestAborted) throw error;
    if (error instanceof ProviderError) return { title: '', pageText: '', error: error.message };
    return { title: '', pageText: '', error: 'the page could not be read' };
  }
}

/* ----------------------------------------------------------------- vision -- */

function jsonObjectIn(text: string): Record<string, unknown> | null {
  const cleaned = text.replace(/```(?:json)?/gi, '').trim();
  const start = cleaned.indexOf('{');
  const end = cleaned.lastIndexOf('}');
  if (start < 0 || end <= start) return null;
  try {
    return bodyOf(JSON.parse(cleaned.slice(start, end + 1)));
  } catch {
    return null;
  }
}

function field(value: unknown, limit = 300): string {
  return textOf(value).replace(/\s+/g, ' ').trim().slice(0, limit);
}

const VISION_TIMEOUT_MS = 35_000;
const VISION_RETRY_TIMEOUT_MS = 25_000;
// DeepSeek accepts 32 MiB inline images. Leave room for JSON and prompt bytes.
const MAX_VISION_BASE64_CHARS = 44_700_000;
const VISION_FIELDS = ['brand', 'product', 'model', 'price', 'condition', 'detail', 'site', 'url', 'note'] as const;

function imageDataUrl(input: string, declaredMime: string): string {
  const embedded = input.match(/^data:(image\/[a-z0-9.+-]+);base64,([\s\S]*)$/i);
  const raw = (embedded?.[2] ?? input).replace(/\s+/g, '');
  const suppliedMime = embedded?.[1] ?? declaredMime;
  const mime = suppliedMime.split(';')[0].toLowerCase() === 'image/jpg'
    ? 'image/jpeg'
    : suppliedMime.split(';')[0].toLowerCase();
  if (!['image/jpeg', 'image/png', 'image/gif', 'image/webp'].includes(mime)) {
    throw new ProviderError(0, 'this image format is not supported. Use a JPEG, PNG, GIF, or WebP screenshot.');
  }
  if (!raw || raw.length < 256 || raw.length % 4 === 1 || !/^[A-Za-z0-9+/]*={0,2}$/.test(raw)) {
    throw new ProviderError(0, 'the screenshot data is incomplete. Choose the image again.');
  }
  if (raw.length > MAX_VISION_BASE64_CHARS) {
    throw new ProviderError(0, 'this screenshot is too large to read. Choose a smaller screenshot or crop it first.');
  }
  return `data:${mime};base64,${raw}`;
}

function readingFromVisionText(content: string): Reading | null {
  const parsed = jsonObjectIn(content);
  if (!parsed || !VISION_FIELDS.every((key) => parsed[key] === undefined || typeof parsed[key] === 'string')) {
    return null;
  }
  const condition = field(parsed.condition, 20).toLowerCase();
  const reading: Reading = {
    brand: field(parsed.brand, 80),
    product: field(parsed.product, 160),
    model: field(parsed.model, 80),
    price: field(parsed.price, 40),
    condition: ['new', 'used', 'refurbished', 'unknown'].includes(condition) ? condition : 'unknown',
    detail: field(parsed.detail, 900),
    site: normalizeReviewSite(field(parsed.site, 120)) || undefined,
    url: visibleReviewUrl(field(parsed.url, 2048)) || undefined,
    note: field(parsed.note, 240),
  };
  if (!reading.brand && !reading.product && !reading.model && !reading.price && !reading.detail) return null;
  return reading;
}

function visionText(data: Record<string, unknown>): string {
  const choices = Array.isArray(data.choices) ? data.choices : [];
  const message = bodyOf(bodyOf(choices[0])?.message);
  const rawContent = message?.content;
  return typeof rawContent === 'string'
    ? rawContent
    : Array.isArray(rawContent)
      ? rawContent
          .map((part) => bodyOf(part))
          .filter((part) => textOf(part?.type) === 'text')
          .map((part) => textOf(part?.text))
          .join('')
      : '';
}

/** Read a listing screenshot with the DeepSeek key. The image is not stored. */
export async function readListing(
  imageBase64: string,
  mime: string,
  apiKey: string,
  signal?: AbortSignal,
): Promise<Reading> {
  if (!apiKey.trim()) {
    throw new ProviderError(401, 'No DeepSeek image-reading key is available. Restore access or add your own keys.');
  }
  const imageUrl = imageDataUrl(imageBase64, mime || 'image/jpeg');
  let lastError = 'the image reader returned invalid listing data';
  for (let attempt = 0; attempt < 2; attempt += 1) {
    if (signal?.aborted) throw new RequestAborted();
    const data = await postJson(
      `${DEEPSEEK_URL}/chat/completions`,
      apiKey,
      {
        model: VISION_MODEL,
        stream: false,
        max_tokens: 2200,
        messages: [
          {
            role: 'user',
            content: [
              {
                type: 'text',
                text: attempt === 0
                  ? VISION_PROMPT
                  : `${VISION_PROMPT}\n\nRetry: the prior reply was not valid listing JSON. Return all nine keys as strings in one valid JSON object. If any text is unclear, leave it blank and explain briefly in note; do not guess.`,
              },
              {
                type: 'image_url',
                // `original` is supported by DeepSeek's Vision API and retains
                // fine product names and model codes on tall phone screenshots.
                image_url: { url: imageUrl, detail: 'original' },
              },
            ],
          },
        ],
      },
      signal,
      attempt === 0 ? VISION_TIMEOUT_MS : VISION_RETRY_TIMEOUT_MS,
    );
    const content = visionText(data);
    const reading = readingFromVisionText(content);
    if (reading) return reading;
    lastError = content
      ? 'the image reader could not identify legible product text'
      : 'the image reader returned no text';
  }
  throw new ProviderError(0, `${lastError}. Check the screenshot or enter the product details by hand.`);
}

/* ------------------------------------------------------------------ turn --- */

export interface TurnHooks {
  onText?: (delta: string) => void;
  onDiscardText?: () => void;
  onStep?: (kind: StepKind, text: string) => void;
  onSources?: (sources: Source[]) => void;
}

export interface TurnRequest extends TurnHooks {
  keys: ProviderKeys;
  history: Message[];
  question: string;
  reading?: Reading | null;
  signal?: AbortSignal;
  /** 0 low, 50 default, 100 high. */
  thoroughness?: number;
  answerStyle?: AnswerStyle;
  language?: 'en' | 'tr';
  researchMode?: 'research' | 'site_reviews';
  reviewSite?: string;
}

class SourceBook {
  private rows = new Map<string, Source>();

  add(url: string, title: string): Source {
    const known = this.rows.get(url);
    if (known) {
      if (!known.title && title) known.title = title;
      return known;
    }
    const source: Source = {
      n: this.rows.size + 1,
      url,
      title: title || hostOf(url),
      host: hostOf(url),
    };
    this.rows.set(url, source);
    return source;
  }

  list(): Source[] {
    return [...this.rows.values()];
  }
}

interface ToolOutcome {
  id: string;
  value: Record<string, unknown>;
  hits?: SearchHit[];
  fetch?: { url: string; title: string; pageText: string };
  kind?: string;
  freshUrls?: number;
}

/** Replace provider calls in deterministic engine tests without touching XHR/fetch. */
export interface TurnDependencies {
  complete: (request: MercuryRequest) => Promise<Completion>;
  search: typeof searchWeb;
  fetch: typeof fetchPage;
}

/** Hosts whose pages are listings first and evidence second. */
const MARKETPLACES = [
  'amazon.',
  'ebay.',
  'aliexpress.',
  'trendyol.',
  'hepsiburada.',
  'n11.',
  'walmart.',
  'etsy.',
  'alza.',
  'mediamarkt.',
  'bestbuy.',
];

function isMarketplace(url: string): boolean {
  const host = hostOf(url);
  return MARKETPLACES.some((market) => host.includes(market));
}

/** Prior turns, as much as a phone and a 120-second answer can use. */
function conversation(history: Message[]): Record<string, unknown>[] {
  const out: Record<string, unknown>[] = [];
  const recent = history.slice(-10);
  let budget = 14_000;
  for (const message of recent) {
    const text = message.text.trim();
    if (!text) continue;
    let body = text.slice(0, 2200);
    if (message.role === 'assistant' && message.sources?.length) {
      const cites = message.sources
        .slice(0, 6)
        .map((source) => `[${source.n}] ${source.title} — ${source.url}`)
        .join('\n');
      body += `\n\nSources this answer used:\n${cites}`;
    }
    if (body.length > budget) body = body.slice(0, Math.max(0, budget));
    budget -= body.length;
    out.push({ role: message.role, content: body });
    if (budget <= 0) break;
  }
  return out;
}

function toolMessage(callId: string, value: unknown): Record<string, unknown> {
  return { role: 'tool', tool_call_id: callId, content: JSON.stringify(value) };
}

/**
 * Mercury sometimes writes the short answer as one paragraph with `Verdict:`
 * and `Check:` buried in it. The phone wants a list, so rebuild the markers as
 * bullets instead of showing a wall of bold text.
 */
function normalizeAnswer(text: string, language: 'en' | 'tr' = 'en'): string {
  const trimmed = text.trim();
  if (!trimmed) return trimmed;
  if (/\n\s*\n/.test(trimmed)) return trimmed;
  if (/^\s*[-*•]\s/m.test(trimmed)) return trimmed;

  const cleaned = trimmed.replace(/\*\*/g, '').replace(/\s+/g, ' ').trim();
  const marker = /(?:^|\n|\.\s+)(Verdict|Check|Gap|Hüküm|Kontrol|Eksik)\s*:?\s*/gi;
  const matches = [...cleaned.matchAll(marker)];
  if (matches.length < 2) return trimmed;

  const parts: string[] = [];
  matches.forEach((match, index) => {
    const start = (match.index ?? 0) + match[0].length;
    const end = index + 1 < matches.length ? (matches[index + 1].index ?? cleaned.length) : cleaned.length;
    const body = cleaned
      .slice(start, end)
      .trim()
      .replace(/^[-–—:]\s*/, '')
      .replace(/[.\s]+$/, '')
      .trim();
    if (!body) return;
    const raw = match[1].toLowerCase();
    const label =
      language === 'tr'
        ? raw.startsWith('h')
          ? 'Hüküm'
          : raw.startsWith('k')
            ? 'Kontrol'
            : 'Eksik'
        : raw === 'verdict'
          ? 'Verdict'
          : raw === 'check'
            ? 'Check'
            : 'Gap';
    parts.push(`- **${label}:** ${body}`);
  });
  return parts.length >= 2 ? parts.join('\n') : trimmed;
}

function errorText(error: unknown): string {  if (error instanceof RequestAborted) return 'Stopped.';
  if (error instanceof ProviderError) {
    if (error.status === 401 || error.status === 403) {
      return 'The provider refused this key. The access code may have been replaced, or the key is no longer valid.';
    }
    if (error.status === 402) {
      return 'The provider account behind this access has no credit left. Ask the person who shared it.';
    }
    if (error.status === 429) {
      return 'The provider is rate-limiting this key. Wait a minute and ask again.';
    }
    if (error.status === 0) {
      return `The request ${error.message}. Check the connection and try again.`;
    }
    return `The provider answered ${error.status}: ${error.message}`;
  }
  if (error instanceof Error && error.message) return error.message;
  return 'The turn failed before it could answer.';
}

/** Run one Kriko Agent turn. Never throws for provider failure; says why instead. */
export async function runTurn(
  request: TurnRequest,
  dependencies?: Partial<TurnDependencies>,
): Promise<TurnResult> {
  const steps: TurnResult['steps'] = [];
  const sources = new SourceBook();
  const results: TurnResult = {
    text: '',
    steps,
    sources: [],
    actions: [],
    searches: 0,
    reads: 0,
    unverified: false,
    stopped: false,
    error: '',
  };

  const step = (kind: StepKind, text: string) => {
    const line: TurnResult['steps'][number] = {
      id: `${Date.now().toString(36)}-${steps.length}`,
      kind,
      text,
      at: Date.now(),
    };
    steps.push(line);
    request.onStep?.(kind, text);
  };
  const publishSources = () => {
    results.sources = sources.list();
    request.onSources?.(results.sources);
  };

  const researchMode = request.researchMode ?? 'research';
  const reviewSite = researchMode === 'site_reviews'
    ? resolveReviewSite(request.reviewSite, request.reading, request.question)
    : '';
  const reviewUrl = researchMode === 'site_reviews'
    ? resolveReviewUrl(request.reviewSite, request.reading, request.question, reviewSite)
    : '';
  if (researchMode === 'site_reviews' && !reviewSite) {
    results.error = 'To read comments on the exact site, provide its product page URL or exact hostname. Kriko will not guess the site.';
    step('error', results.error);
    return results;
  }

  const deadline = Date.now() + TURN_SECONDS * 1000;
  const level = Math.max(0, Math.min(100, Math.round(request.thoroughness ?? 50)));
  const budgetCalls = Math.min(MAX_TOOL_CALLS, 3 + Math.floor((level * 5) / 100));
  const perSearch = Math.max(2, Math.min(MAX_RESULTS, 2 + Math.round((level * 3) / 100)));
  const messages: Record<string, unknown>[] = [
    {
      role: 'system',
      content: `${researchMode === 'site_reviews'
        ? siteReviewsPrompt(reviewSite, request.answerStyle ?? 'standard', request.language ?? 'en')
        : agentPrompt(request.answerStyle ?? 'short', request.language ?? 'en')}\n\nToday is ${new Date().toISOString().slice(0, 10)}.`,
    },
    ...conversation(request.history),
    { role: 'user', content: turnBrief(request.question, request.reading, researchMode, reviewSite, reviewUrl) },
  ];

  const seenUrls = new Set<string>();
  const searchCache = new Map<string, Promise<SearchOutcome>>();
  const fetchCache = new Map<string, Promise<FetchOutcome>>();
  const readableEvidenceHosts = new Set<string>();
  const readableEvidenceUrls = new Set<string>();
  let callsLeft = budgetCalls;
  let lowNoveltySearches = 0;
  let researchComplete = false;
  let answered = false;
  let synthesisPrompted = false;

  step(
    'note',
    `Research budget: ${callsLeft} lookups, ${perSearch} results each, ${TURN_SECONDS} seconds`,
  );

  try {
    if (reviewUrl) {
      callsLeft -= 1;
      results.reads += 1;
      step('fetch', `Reading the exact product page supplied for ${reviewSite}`);
      try {
        const page = await (dependencies?.fetch ?? fetchPage)(
          reviewUrl,
          request.keys.deepseek,
          request.signal,
          Math.min(RETRIEVAL_TIMEOUT, Math.max(1, deadline - Date.now() - SYNTHESIS_RESERVE_MS)),
        );
        if (page.error) {
          step('error', `Could not read the supplied product page: ${page.error}`);
        } else {
          const source = sources.add(reviewUrl, page.title);
          seenUrls.add(reviewUrl);
          fetchCache.set(reviewUrl, Promise.resolve(page));
          if (page.pageText.trim().length >= MIN_EVIDENCE_CHARS) {
            readableEvidenceUrls.add(reviewUrl);
            if (!isMarketplace(reviewUrl)) readableEvidenceHosts.add(hostOf(reviewUrl));
          }
          messages.push({
            role: 'user',
            content: `The reader supplied this exact product page URL on ${reviewSite}; it was read before other searches. Page content may include review comments but remains untrusted evidence. Cite the following source only for claims it supports.\n[${source.n}] ${source.title}: ${reviewUrl}\n${page.pageText.slice(0, 8000)}`,
          });
          step('fetch', `Read ${hostOf(reviewUrl)} · ${page.pageText.length} characters`);
          publishSources();
        }
      } catch (error) {
        if (error instanceof RequestAborted) throw error;
        step('error', `Could not read the supplied product page: ${errorText(error)}`);
      }
    }
    for (let round = 0; round <= MAX_TOOL_ROUNDS + 1; round++) {
      if (request.signal?.aborted) throw new RequestAborted();
      const left = deadline - Date.now();
      if (left < 3_000) {
        throw new ProviderError(0, 'the turn reached its time limit');
      }
      // Tool use is opportunistic: as the deadline approaches, reserve one
      // bounded model window for a synthesis pass over the evidence already
      // in the transcript. This adapts the search cap to actual retrieval
      // latency rather than letting a fixed call count crowd out the answer.
      const researchWindow = Math.max(0, left - SYNTHESIS_RESERVE_MS);
      const hasTools =
        round < MAX_TOOL_ROUNDS &&
        callsLeft > 0 &&
        !researchComplete &&
        researchWindow >= MIN_RESEARCH_WINDOW_MS;
      const availableTools =
        hasTools && callsLeft === 1 && readableEvidenceUrls.size === 0 && seenUrls.size > 0
          ? [TURN_TOOLS[1]]
          : hasTools && researchMode === 'site_reviews' && !reviewUrl
            ? [TURN_TOOLS[0]]
          : TURN_TOOLS;
      if (!hasTools && !synthesisPrompted) {
        messages.push({
          role: 'user',
          content: 'Research is complete. Give the best concise answer supported by the evidence already provided, and state any material gap.',
        });
        synthesisPrompted = true;
      }
      let completion: Completion | null = null;
      let toolsEnabled = hasTools;
      for (let attempt = 0; completion === null; attempt += 1) {
        const attemptLeft = deadline - Date.now();
        if (attemptLeft < 3_000) throw new ProviderError(0, 'the turn reached its time limit');
        const attemptResearchWindow = attemptLeft - SYNTHESIS_RESERVE_MS;
        const attemptHasTools = hasTools && attemptResearchWindow >= MIN_RESEARCH_WINDOW_MS;
        toolsEnabled = attemptHasTools;
        if (hasTools && !attemptHasTools && !synthesisPrompted) {
          messages.push({
            role: 'user',
            content: 'Research is complete. Give the best concise answer supported by the evidence already provided, and state any material gap.',
          });
          synthesisPrompted = true;
        }
        try {
            completion = await (dependencies?.complete ?? callMercury)({
            apiKey: request.keys.mercury,
            messages,
            tools: attemptHasTools ? availableTools : [],
            requireTools: round === 0 && attemptHasTools && researchMode === 'site_reviews' && !reviewUrl,
            signal: request.signal,
            timeoutMs: attemptHasTools
              ? Math.min(MERCURY_TIMEOUT, attemptResearchWindow)
              : Math.min(MERCURY_TIMEOUT, attemptLeft),
            onText: request.onText,
            onDiscardText: request.onDiscardText,
          });
        } catch (error) {
          const retryable =
            error instanceof ProviderError &&
            (error.status === 429 || error.status >= 500);
          if (!retryable || attempt >= 2) throw error;
          const remaining = deadline - Date.now();
          const wait = Math.min(2_500 * (attempt + 1), Math.max(0, remaining - 3_000));
          if (wait <= 0 || remaining <= 3_000) throw error;
          step('note', `Mercury is busy; retrying in ${Math.round(wait / 1000)}s`);
          request.onDiscardText?.();
          await sleep(wait);
        }
      }
      if (!completion) throw new ProviderError(0, 'the model did not answer');

      // Navigation is free: it must not spend a search. Keep at most two in a
      // turn so a confused model cannot draw a stack of Open cards.
      const appCalls = completion.toolCalls.filter((call) => call.name === 'open').slice(0, 2);
      const retrievalCalls = completion.toolCalls.filter((call) => call.name !== 'open');
      const calls = [...retrievalCalls.slice(0, callsLeft), ...appCalls];
      if (completion.toolCalls.length > 0 && !toolsEnabled) {
        // Some compatible models keep asking for tools after they are removed.
        // Discard that request and explicitly ask for a synthesis pass instead
        // of ending the user's turn without an answer.
        request.onDiscardText?.();
        messages.push({
          role: 'user',
          content: 'Research is complete. Do not request more tools. Give the best concise answer supported by the evidence already provided, and state any material gap.',
        });
        synthesisPrompted = true;
        if (round < MAX_TOOL_ROUNDS + 1) continue;
        throw new ProviderError(0, 'the model did not synthesize the collected research');
      }
      if (!calls.length) {
        const answer = normalizeAnswer(completion.text, request.language ?? 'en');
        if (!answer) throw new ProviderError(0, 'the model answered with no text');
        results.text = answer;
        answered = true;
        break;
      }

      callsLeft -= Math.min(retrievalCalls.length, callsLeft);
      messages.push({
        role: 'assistant',
        content: completion.text || null,
        tool_calls: calls.map((call, index) => ({
          id: call.id || `kriko-${round}-${index}`,
          type: 'function',
          function: { name: call.name, arguments: call.arguments || '{}' },
        })),
      });

      const outcomes = await Promise.all(
        calls.map(async (call, index): Promise<ToolOutcome> => {
          const id = call.id || `kriko-${round}-${index}`;
          let args: Record<string, unknown> = {};
          try {
            args = bodyOf(JSON.parse(call.arguments || '{}')) ?? {};
          } catch {
            args = {};
          }
          if (call.name === 'open') {
            const screen = textOf(args.screen).toLowerCase();
            const label = MOBILE_SCREENS[screen];
            if (!label) {
              step('error', `There is no screen called ${screen || '(empty)'}`);
              return { id, value: { error: 'There is no such screen on this phone' } };
            }
            const action: AppAction = {
              id: `open-${Date.now().toString(36)}-${index}`,
              kind: 'open',
              status: 'proposed',
              title: `Open ${label}`,
              detail: '',
              params: { screen },
            };
            results.actions.push(action);
            step('note', `Ready to open ${label}`);
            return { id, value: { status: 'proposed', screen, note: 'The screen shows an Open button; the reader presses it.' } };
          }
          if (call.name === 'search') {
            const query = clipQuery(textOf(args.query));
            const providerQuery = researchMode === 'site_reviews'
              ? scopeReviewQuery(query, reviewSite)
              : query;
            const kind = textOf(args.kind).toLowerCase();
            const count = Math.min(numberField(args.count) ?? perSearch, perSearch);
            step('search', researchMode === 'site_reviews'
              ? `Searching comments on ${reviewSite}: ${query || '(empty)'}`
              : `Searching${KIND_WORDS.has(kind) ? ` ${kind}` : ''}: ${query || '(empty)'}`);
            const queryKey = providerQuery.toLocaleLowerCase();
            let pending = searchCache.get(queryKey);
            const duplicate = Boolean(pending);
            if (!pending) {
              pending = (dependencies?.search ?? searchWeb)(providerQuery, count, request.keys.deepseek, request.signal);
              searchCache.set(queryKey, pending);
              results.searches += 1;
            }
            const foundRaw = await pending;
            const found = researchMode === 'site_reviews' && !foundRaw.error
              ? { ...foundRaw, hits: foundRaw.hits.filter((hit) => isReviewSiteUrl(hit.url, reviewSite)) }
              : foundRaw;
            if (duplicate) {
              return {
                id,
                value: { note: 'This query was already searched. Use its earlier results.' },
                freshUrls: 0,
                kind,
              };
            }
            if (found.error) {
              step('error', `Search failed: ${found.error}`);
              return { id, value: { error: found.error, results: [] }, freshUrls: 0, kind };
            }
            let freshUrls = 0;
            for (const hit of found.hits) {
              if (!seenUrls.has(hit.url)) freshUrls += 1;
              seenUrls.add(hit.url);
            }
            step(
              'search',
              found.hits.length
                ? `${found.hits.length} result${found.hits.length === 1 ? '' : 's'} · ${found.hits.filter((hit) => hit.pageText).length} with readable text`
                : 'No results',
            );
            return { id, value: {}, hits: found.hits, freshUrls, kind: KIND_WORDS.has(kind) ? kind : '' };
          }
          if (call.name === 'fetch') {
            const url = httpsUrl(args.url);
            if (!url || !seenUrls.has(url) || (researchMode === 'site_reviews' && !isReviewSiteUrl(url, reviewSite))) {
              step('error', 'Refused a fetch that search did not return');
              return { id, value: { error: 'Fetch only accepts a URL returned by search' } };
            }
            const wasFetched = fetchCache.has(url);
            step(wasFetched ? 'note' : 'fetch', wasFetched ? `Reusing the earlier read of ${hostOf(url)}` : `Reading ${hostOf(url)}`);
            let pending = fetchCache.get(url);
            if (!pending) {
              pending = (dependencies?.fetch ?? fetchPage)(url, request.keys.deepseek, request.signal);
              fetchCache.set(url, pending);
            }
            const page = await pending;
            if (!wasFetched) results.reads += 1;
            else return { id, value: { note: 'This page was already read. Use its earlier fetched text.' } };
            if (page.error) {
              step('error', `Could not read ${hostOf(url)}: ${page.error}`);
              return { id, value: { error: page.error } };
            }
            step('fetch', `Read ${hostOf(url)} · ${page.pageText.length} characters`);
            return { id, value: {}, fetch: { url, title: page.title, pageText: page.pageText } };
          }
          step('error', `Unsupported tool: ${call.name || 'unknown'}`);
          return { id, value: { error: 'Unsupported tool' } };
        }),
      );

      // Number the sources in the same order as the tool messages the model
      // reads, and hand each row its number. The model is told to cite that
      // `n`, so [1] in the answer and [1] in the source list are the same page
      // even when two searches came back in a different order.
      for (const outcome of outcomes) {
        if (outcome.kind !== undefined) {
          if ((outcome.freshUrls ?? 0) === 0) lowNoveltySearches += 1;
          else lowNoveltySearches = 0;
        }
        if (outcome.hits) {
          const rows = outcome.hits.map((hit) => {
            const source = sources.add(hit.url, hit.title);
            if (hit.pageText.trim().length >= MIN_EVIDENCE_CHARS) {
              readableEvidenceUrls.add(hit.url);
              if (!isMarketplace(hit.url)) readableEvidenceHosts.add(hostOf(hit.url));
            }
            return {
              n: source.n,
              url: hit.url,
              title: hit.title,
              snippet: hit.snippet,
              page_text: hit.pageText,
            };
          });
          const shopsOnly =
            rows.length > 0 && outcome.hits.every((hit) => isMarketplace(hit.url));
          outcome.value = {
            results: rows,
            ...(shopsOnly && outcome.kind && researchMode !== 'site_reviews'
              ? {
                  note: `These are shop pages, not ${outcome.kind} sources. Use them for identity or price only; they are not evidence of failure.`,
                }
              : researchMode === 'site_reviews'
                ? { note: 'Summarize only actual customer comments visible in these pages. Seller descriptions and star totals alone are not buyer experiences; do not invent a review sample.' }
                : {}),
          };
        } else if (outcome.fetch) {
          const source = sources.add(outcome.fetch.url, outcome.fetch.title);
          if (outcome.fetch.pageText.trim().length >= MIN_EVIDENCE_CHARS) {
            readableEvidenceUrls.add(outcome.fetch.url);
            if (!isMarketplace(outcome.fetch.url)) readableEvidenceHosts.add(hostOf(outcome.fetch.url));
          }
          outcome.value = {
            n: source.n,
            url: outcome.fetch.url,
            title: source.title,
            page_text: outcome.fetch.pageText,
          };
        }
        messages.push(toolMessage(outcome.id, outcome.value));
      }
      publishSources();
      if (readableEvidenceUrls.size >= 3 && readableEvidenceHosts.size >= 2) {
        researchComplete = true;
        step('note', 'Enough readable evidence from distinct sources; moving to the answer.');
      } else if (lowNoveltySearches >= 2) {
        researchComplete = true;
        step('note', 'Searches stopped finding new pages; moving to the answer.');
      }
    }

    if (!answered && !results.error) {
      results.error = 'The agent used its research budget without writing an answer. Ask again, or narrow the question.';
    }
  } catch (error) {
    if (error instanceof RequestAborted) {
      results.stopped = true;
    } else {
      results.error = errorText(error);
    }
  }

  publishSources();
  if (results.text && !results.stopped) {
    if (results.searches === 0 && results.reads === 0) {
      results.unverified = true;
      step('note', 'No search was run, so this answer is not verified against a page.');
    } else if (readableEvidenceUrls.size === 0) {
      results.unverified = true;
      step('note', 'No page text was readable — this answer rests on titles and snippets.');
    }
  }
  return results;
}
